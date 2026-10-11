"""
smtpserver.py - Servidor SMTP implementado con Twisted
Uso: python smtpserver.py -d <domains> -s <mail-storage> -p <port>

Soporta:
  - Envío y recepción de correos (SMTP)
  - Capa segura TLS/SSL
  - Validación de dominios aceptados
  - Recepción de archivos adjuntos con MIME
  - Notificación XMPP al recibir correo nuevo
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime

from twisted.internet import reactor, defer, ssl
from twisted.mail import smtp
from twisted.python import log

# ─────────────────────────────────────────────
# Configuración del logger
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SMTP] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Redirige logs de Twisted al logger estándar
observer = log.PythonLoggingObserver()
observer.start()


# ─────────────────────────────────────────────
# Notificador XMPP (importado de xmpp_notifier)
# ─────────────────────────────────────────────
def notify_xmpp(recipient_user, sender_address):
    """
    Carga la configuración XMPP desde config.json y envía
    una notificación al usuario indicado cuando llega un correo nuevo.
    """
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if not os.path.exists(config_path):
            logger.warning("config.json no encontrado, no se enviará notificación XMPP.")
            return

        with open(config_path, "r") as f:
            config = json.load(f)

        users = config.get("users", {})
        if recipient_user not in users:
            logger.warning(f"Usuario '{recipient_user}' no encontrado en config.json.")
            return

        xmpp_jid = users[recipient_user].get("xmpp_jid")
        if not xmpp_jid:
            logger.warning(f"El usuario '{recipient_user}' no tiene xmpp_jid configurado.")
            return

        # Importación diferida para no romper el servidor si slixmpp no está instalado
        from xmpp_notifier import notify
        message = f"Tienes un nuevo correo electrónico de: {sender_address}"
        notify(xmpp_jid, message)
        logger.info(f"Notificación XMPP enviada a {xmpp_jid}")

    except ImportError:
        logger.error("No se pudo importar xmpp_notifier. Verifica que slixmpp esté instalado.")
    except Exception as e:
        logger.error(f"Error al enviar notificación XMPP: {e}")


# ─────────────────────────────────────────────
# Clase que almacena el mensaje recibido
# ─────────────────────────────────────────────
class MailMessage:
    """
    Acumula las líneas del correo recibido por SMTP.
    Al finalizar (eomReceived), guarda el archivo .eml en disco
    y notifica al usuario vía XMPP.
    Soporta MIME completo: texto plano, HTML y archivos adjuntos.
    """

    implements = [smtp.IMessage]

    def __init__(self, recipient_address, mail_storage, sender_address="desconocido"):
        self.recipient_address = recipient_address  # ej: usuario@dominio.com
        self.mail_storage = mail_storage
        self.sender_address = sender_address
        self.lines = []

    def lineReceived(self, line):
        """Recibe cada línea del cuerpo del correo (incluyendo cabeceras y MIME)."""
        self.lines.append(line)

    def eomReceived(self):
        """
        Fin del mensaje. Guarda el .eml en la carpeta del destinatario.
        El nombre del archivo incluye timestamp para garantizar unicidad.
        """
        try:
            # Carpeta del destinatario: mailstorage/usuario@dominio.com/
            user_folder = os.path.join(self.mail_storage, self.recipient_address)
            os.makedirs(user_folder, exist_ok=True)

            # Nombre de archivo único con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{timestamp}.eml"
            filepath = os.path.join(user_folder, filename)

            # Escribe todas las líneas recibidas al archivo
            with open(filepath, "wb") as f:
                for line in self.lines:
                    f.write(line + b"\n")

            logger.info(f"Correo guardado: {filepath}")

            # Notificación XMPP al usuario
            recipient_user = self.recipient_address.split("@")[0]
            notify_xmpp(recipient_user, self.sender_address)

        except Exception as e:
            logger.error(f"Error al guardar el correo: {e}")
            return defer.fail(e)

        return defer.succeed(None)

    def connectionLost(self):
        """Se llama si la conexión se pierde antes de completar la recepción."""
        logger.warning(f"Conexión perdida durante recepción de correo para {self.recipient_address}")
        self.lines = []


# ─────────────────────────────────────────────
# Clase de entrega de correo
# ─────────────────────────────────────────────
class MailDelivery:
    """
    Implementa IMessageDelivery de Twisted.
    Se encarga de:
      - Validar el remitente (acepta cualquiera)
      - Validar el destinatario (solo dominios aceptados)
      - Construir el objeto MailMessage para cada destinatario válido
    """

    def __init__(self, domains, mail_storage):
        """
        domains     : lista de dominios aceptados por este servidor
        mail_storage: ruta base donde se almacenan los correos
        """
        self.domains = [d.lower() for d in domains]
        self.mail_storage = mail_storage
        self._current_sender = "desconocido"

    def receivedHeader(self, helo, origin, recipients):
        """
        Genera la cabecera 'Received:' que se agrega al mensaje.
        helo    : tupla (hostname, ip) del cliente que se conectó
        origin  : dirección del remitente (MAIL FROM)
        recipients: lista de destinatarios (RCPT TO)
        """
        helo_host = helo[0] if helo and helo[0] else b"desconocido"
        if isinstance(helo_host, str):
            helo_host = helo_host.encode()
        timestamp = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
        header = (
            f"Received: from {helo_host.decode(errors='replace')} "
            f"by smtpserver (Twisted) ; {timestamp}"
        )
        return header.encode()

    def validateFrom(self, helo, origin):
        """
        Valida el remitente. Este servidor acepta correos de cualquier origen.
        Si se quisiera restringir, se lanzaría SMTPBadSender.
        origin es un objeto smtp.Address.
        """
        self._current_sender = str(origin)
        logger.info(f"Remitente aceptado: {origin}")
        return origin

    def validateTo(self, user):
        """
        Valida el destinatario. Solo acepta correos dirigidos a los dominios configurados.
        user.dest es un objeto smtp.Address con atributo 'domain'.
        Lanza SMTPBadRcpt si el dominio no está en la lista de aceptados.
        """
        address = str(user.dest)
        domain = address.split("@")[-1].lower()

        if domain in self.domains:
            logger.info(f"Destinatario aceptado: {address}")
            sender = self._current_sender
            storage = self.mail_storage
            # Retorna un callable que construye el MailMessage al iniciar DATA
            return lambda: MailMessage(address, storage, sender)
        else:
            logger.warning(f"Dominio rechazado: {domain} (no en {self.domains})")
            raise smtp.SMTPBadRcpt(user)


# ─────────────────────────────────────────────
# Factory del servidor SMTP
# ─────────────────────────────────────────────
class CustomSMTPFactory(smtp.SMTPFactory):
    """
    Factory de Twisted que crea instancias del protocolo SMTP.
    Inyecta el objeto MailDelivery en cada conexión entrante.
    """

    def __init__(self, domains, mail_storage):
        smtp.SMTPFactory.__init__(self)
        self.domains = domains
        self.mail_storage = mail_storage
        # Asegura que el directorio de almacenamiento exista
        os.makedirs(mail_storage, exist_ok=True)

    def buildProtocol(self, addr):
        """
        Construye el protocolo SMTP para cada conexión entrante.
        Asigna un nuevo MailDelivery a cada conexión.
        """
        p = smtp.SMTPFactory.buildProtocol(self, addr)
        p.delivery = MailDelivery(self.domains, self.mail_storage)
        return p


# ─────────────────────────────────────────────
# Punto de entrada principal
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Servidor SMTP con Twisted. Soporta TLS, validación de dominios y MIME."
    )
    parser.add_argument(
        "-d", "--domains",
        nargs="+",
        required=True,
        help="Lista de dominios aceptados. Ejemplo: -d dominio.com otro.com"
    )
    parser.add_argument(
        "-s", "--storage",
        required=True,
        help="Ruta al directorio de almacenamiento de correos. Ejemplo: -s ./mailstorage"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=2525,
        help="Puerto TCP para el servidor SMTP (default: 2525)"
    )
    parser.add_argument(
        "--ssl-port",
        type=int,
        default=4650,
        help="Puerto para SMTP sobre SSL/TLS (default: 4650)"
    )
    parser.add_argument(
        "--cert",
        default="certs/server.crt",
        help="Ruta al certificado SSL (default: certs/server.crt)"
    )
    parser.add_argument(
        "--key",
        default="certs/server.key",
        help="Ruta a la llave privada SSL (default: certs/server.key)"
    )

    args = parser.parse_args()

    # Crea la carpeta de almacenamiento si no existe
    os.makedirs(args.storage, exist_ok=True)

    factory = CustomSMTPFactory(args.domains, args.storage)

    # ── Puerto SMTP plano ──────────────────────────────────────────────
    reactor.listenTCP(args.port, factory)
    logger.info(f"SMTP escuchando en TCP puerto {args.port}")
    logger.info(f"Dominios aceptados: {args.domains}")

    # ── Puerto SMTP con SSL/TLS ────────────────────────────────────────
    if os.path.exists(args.cert) and os.path.exists(args.key):
        try:
            ssl_context = ssl.DefaultOpenSSLContextFactory(args.key, args.cert)
            reactor.listenSSL(args.ssl_port, factory, ssl_context)
            logger.info(f"SMTP+SSL escuchando en puerto {args.ssl_port}")
        except Exception as e:
            logger.error(f"No se pudo iniciar SSL: {e}. Solo se usará el puerto plano.")
    else:
        logger.warning(
            f"Certificados no encontrados en {args.cert} / {args.key}. "
            f"SSL deshabilitado. Genera con: "
            f"openssl req -newkey rsa:2048 -nodes -keyout {args.key} -x509 -days 365 -out {args.cert}"
        )

    logger.info("Iniciando reactor de Twisted...")
    reactor.run()


if __name__ == "__main__":
    main()
