"""
pop3server.py - Servidor POP3 implementado con Twisted
Uso: python pop3server.py -s <mail-storage> -p <port>

Funcionalidades:
  - Autenticación de usuarios contra config.json
  - Descarga de correos (.eml) por usuario
  - Eliminación de correos tras la descarga (comportamiento estándar POP3)
  - Soporte SSL/TLS
  - Compatible con clientes como Thunderbird, Outlook, etc.
"""

import os
import sys
import json
import logging
import argparse

from twisted.internet import reactor, defer, ssl
from twisted.mail import pop3
from twisted.cred import credentials, portal, error as credError
from twisted.internet.protocol import ServerFactory
from twisted.python import log

# ─────────────────────────────────────────────
# Configuración del logger
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POP3] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

observer = log.PythonLoggingObserver()
observer.start()


# ─────────────────────────────────────────────
# Buzón de correo del usuario
# ─────────────────────────────────────────────
class SimpleMailbox:
    """
    Implementa IMailbox de Twisted para POP3.

    Gestiona los correos de un usuario específico:
      - Lista los mensajes disponibles en su carpeta
      - Permite leer cada mensaje individualmente
      - Marca mensajes para eliminar (se eliminan al hacer sync)

    Los correos se almacenan como archivos .eml en:
        mail_storage/usuario@dominio.com/archivo.eml
    """

    def __init__(self, user_folder):
        """
        user_folder (str): Ruta a la carpeta de correos del usuario.
                           Ej: ./mailstorage/juan@dominio.com
        """
        self.user_folder = user_folder
        os.makedirs(user_folder, exist_ok=True)

        # Lista de rutas absolutas a los .eml, ordenados por nombre (= por fecha)
        self.messages = sorted([
            os.path.join(user_folder, fname)
            for fname in os.listdir(user_folder)
            if fname.endswith(".eml")
        ])

        # Conjunto de índices marcados para eliminación
        self._deleted = set()

        logger.info(f"Buzón cargado: {user_folder} ({len(self.messages)} mensajes)")

    def listMessages(self, index=None):
        """
        Retorna el tamaño en bytes de los mensajes.
        Los mensajes marcados para eliminar retornan 0.
        """
        if index is not None:
            if index in self._deleted:
                return defer.succeed(0)
            return defer.succeed(os.path.getsize(self.messages[index]))

        sizes = []
        for i, path in enumerate(self.messages):
            if i in self._deleted:
                sizes.append(0)
            else:
                sizes.append(os.path.getsize(path))
        return defer.succeed(sizes)

    def getMessage(self, index):
        """
        Retorna el contenido de un mensaje como objeto de archivo abierto.
        Twisted POP3 lee de este objeto para enviarlo al cliente.
        """
        if index in self._deleted:
            raise ValueError(f"Mensaje {index} está marcado para eliminación.")
        if index >= len(self.messages):
            raise IndexError(f"Índice {index} fuera de rango.")

        logger.info(f"Leyendo mensaje {index}: {os.path.basename(self.messages[index])}")
        return open(self.messages[index], "rb")

    def getUidl(self, index):
        """
        Retorna el UIDL (identificador único) del mensaje.
        Se usa el nombre del archivo como identificador único.
        """
        return os.path.basename(self.messages[index])

    def deleteMessage(self, index):
        """
        Marca un mensaje para eliminación.
        El archivo físico NO se borra hasta que se llame sync().
        """
        self._deleted.add(index)
        logger.info(f"Mensaje {index} marcado para eliminación.")

    def undeleteMessages(self):
        """
        Desmarca todos los mensajes (RSET).
        """
        self._deleted.clear()
        logger.info("Todos los mensajes desmarcados (RSET).")

    def sync(self):
        """
        Elimina físicamente los mensajes marcados.
        Se llama al cerrar la sesión POP3 correctamente (QUIT).
        """
        deleted_count = 0
        for index in sorted(self._deleted, reverse=True):
            try:
                os.remove(self.messages[index])
                logger.info(f"Mensaje eliminado: {os.path.basename(self.messages[index])}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error al eliminar mensaje {index}: {e}")

        self._deleted.clear()
        logger.info(f"Sync completado. Mensajes eliminados: {deleted_count}")
        return defer.succeed(None)

    def getMessageCount(self):
        """Retorna el número de mensajes no marcados para eliminación."""
        return len(self.messages) - len(self._deleted)

    def getMailboxSize(self):
        """Retorna el tamaño total del buzón en bytes."""
        total = 0
        for i, path in enumerate(self.messages):
            if i not in self._deleted:
                total += os.path.getsize(path)
        return total


# ─────────────────────────────────────────────
# Realm: conecta el usuario autenticado con su buzón
# ─────────────────────────────────────────────
class MailRealm:
    """
    Twisted Cred Realm para POP3.
    Una vez autenticado el usuario, construye y retorna su SimpleMailbox.
    """

    def __init__(self, mail_storage, domains):
        self.mail_storage = mail_storage
        self.domains = domains

    def requestAvatar(self, avatarId, mind, *interfaces):
        """
        Construye el buzón para el usuario autenticado.
        """
        if pop3.IMailbox not in interfaces:
            raise NotImplementedError("Solo se soporta IMailbox para POP3.")

        username = avatarId.decode("utf-8") if isinstance(avatarId, bytes) else avatarId

        # Busca la carpeta del usuario probando usuario@dominio para cada dominio
        user_folder = None
        for domain in self.domains:
            candidate = os.path.join(self.mail_storage, f"{username}@{domain}")
            if os.path.exists(candidate):
                user_folder = candidate
                break

        # Si no existe ninguna carpeta, la crea con el primer dominio
        if user_folder is None:
            first_domain = self.domains[0] if self.domains else "localhost"
            user_folder = os.path.join(self.mail_storage, f"{username}@{first_domain}")
            os.makedirs(user_folder, exist_ok=True)
            logger.info(f"Carpeta creada para usuario nuevo: {user_folder}")

        mailbox = SimpleMailbox(user_folder)
        logger.info(f"Sesión POP3 iniciada para: {username} ({mailbox.getMessageCount()} mensajes)")

        return pop3.IMailbox, mailbox, lambda: logger.info(f"Sesión POP3 cerrada: {username}")


# ─────────────────────────────────────────────
# Checker: verifica usuario y contraseña
# ─────────────────────────────────────────────
class ConfigFileChecker:
    """
    Twisted Cred Checker que valida credenciales contra config.json.
    """

    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, config_path="config.json"):
        self.config_path = config_path

    def _load_users(self):
        if not os.path.exists(self.config_path):
            logger.error(f"config.json no encontrado: {self.config_path}")
            return {}
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
            return config.get("users", {})
        except Exception as e:
            logger.error(f"Error al leer config.json: {e}")
            return {}

    def requestAvatarId(self, creds):
        """
        Verifica las credenciales del usuario contra config.json.
        """
        username = creds.username.decode("utf-8") if isinstance(creds.username, bytes) else creds.username
        password = creds.password.decode("utf-8") if isinstance(creds.password, bytes) else creds.password

        users = self._load_users()

        if username in users and users[username].get("password") == password:
            logger.info(f"Autenticación exitosa: {username}")
            return defer.succeed(creds.username)
        else:
            logger.warning(f"Autenticación fallida para: {username}")
            return defer.fail(credError.UnauthorizedLogin())


# ─────────────────────────────────────────────
# Factory POP3 manual (POP3Factory fue eliminado
# en versiones modernas de Twisted)
# ─────────────────────────────────────────────
class POP3Factory(ServerFactory):
    """
    Factory que construye instancias del protocolo POP3.
    Reemplaza el POP3Factory que fue removido de Twisted.
    Recibe el portal de autenticación e inyecta en cada conexión.
    """

    protocol = pop3.POP3

    def __init__(self, portal):
        self.portal = portal

    def buildProtocol(self, addr):
        p = self.protocol()
        p.portal = self.portal
        p.factory = self
        logger.info(f"Nueva conexión POP3 desde: {addr}")
        return p


# ─────────────────────────────────────────────
# Punto de entrada principal
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Servidor POP3 con Twisted. Soporta SSL y autenticación por config.json."
    )
    parser.add_argument(
        "-s", "--storage",
        required=True,
        help="Ruta al directorio de almacenamiento de correos. Ejemplo: -s ./mailstorage"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=1100,
        help="Puerto TCP para el servidor POP3 (default: 1100)"
    )
    parser.add_argument(
        "--ssl-port",
        type=int,
        default=9950,
        help="Puerto para POP3 sobre SSL/TLS (default: 9950)"
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
    parser.add_argument(
        "--config",
        default="config.json",
        help="Ruta al archivo config.json (default: config.json)"
    )
    parser.add_argument(
        "-d", "--domains",
        nargs="+",
        default=["localhost"],
        help="Lista de dominios del servidor (default: localhost)"
    )

    args = parser.parse_args()

    os.makedirs(args.storage, exist_ok=True)

    if not os.path.exists(args.config):
        logger.error(f"config.json no encontrado: {args.config}")
        sys.exit(1)

    # Construye el portal de autenticación
    realm = MailRealm(args.storage, args.domains)
    checker = ConfigFileChecker(args.config)

    p = portal.Portal(realm)
    p.registerChecker(checker)

    factory = POP3Factory(p)

    # Puerto POP3 plano
    reactor.listenTCP(args.port, factory)
    logger.info(f"POP3 escuchando en TCP puerto {args.port}")

    # Puerto POP3 con SSL
    if os.path.exists(args.cert) and os.path.exists(args.key):
        try:
            ssl_context = ssl.DefaultOpenSSLContextFactory(args.key, args.cert)
            reactor.listenSSL(args.ssl_port, factory, ssl_context)
            logger.info(f"POP3+SSL escuchando en puerto {args.ssl_port}")
        except Exception as e:
            logger.error(f"No se pudo iniciar SSL: {e}. Solo se usará el puerto plano.")
    else:
        logger.warning(
            f"Certificados no encontrados. SSL deshabilitado. "
            f"Generá con: openssl req -newkey rsa:2048 -nodes "
            f"-keyout {args.key} -x509 -days 365 -out {args.cert}"
        )

    logger.info(f"Almacenamiento: {os.path.abspath(args.storage)}")
    logger.info(f"Dominios: {args.domains}")
    logger.info("Iniciando reactor de Twisted...")
    reactor.run()


if __name__ == "__main__":
    main()
