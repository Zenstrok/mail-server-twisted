"""
xmpp_notifier.py - Servicio de notificaciones XMPP
Se importa desde smtpserver.py para notificar al usuario cuando llega un correo nuevo.
También puede ejecutarse de forma independiente para pruebas.

Uso independiente (prueba):
    python xmpp_notifier.py --to usuario@jabber.fr --message "Tienes correo nuevo"
"""

import os
import sys
import json
import logging
import asyncio
import argparse
import threading

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Cliente XMPP basado en slixmpp (asyncio puro)
# ─────────────────────────────────────────────
class XMPPNotifierBot:
    """
    Bot XMPP que envía un mensaje a un usuario y luego se desconecta.
    slixmpp es completamente asyncio — no usa process() sino await.

    Parámetros:
        jid       (str): JID del bot notificador. Ej: notificador@jabber.fr
        password  (str): Contraseña del bot.
        recipient (str): JID del destinatario de la notificación.
        message   (str): Texto del mensaje a enviar.
    """

    def __init__(self, jid, password, recipient, message):
        self.jid = jid
        self.password = password
        self.recipient = recipient
        self.message = message

    async def run(self):
        """
        Conecta al servidor XMPP, envía el mensaje y desconecta.
        Debe ejecutarse dentro de un event loop de asyncio.
        """
        import slixmpp

        # Evento para saber cuándo terminar
        done = asyncio.Event()

        client = slixmpp.ClientXMPP(self.jid, self.password)

        async def on_session_start(event):
            try:
                client.send_presence()
                await client.get_roster()
                client.send_message(
                    mto=self.recipient,
                    mbody=self.message,
                    mtype="chat"
                )
                logger.info(f"Notificación XMPP enviada a: {self.recipient}")
            except Exception as e:
                logger.error(f"Error durante la sesión XMPP: {e}")
            finally:
                client.disconnect()
                done.set()

        def on_failed_auth(event):
            logger.error(f"Autenticación XMPP fallida para: {self.jid}")
            done.set()

        def on_disconnected(event):
            done.set()

        client.add_event_handler("session_start", on_session_start)
        client.add_event_handler("failed_auth", on_failed_auth)
        client.add_event_handler("disconnected", on_disconnected)

        client.connect()

        # Espera hasta que se envíe el mensaje y se desconecte
        await asyncio.wait_for(done.wait(), timeout=15)


# ─────────────────────────────────────────────
# Función que corre el bot en un hilo separado
# (para no bloquear el reactor de Twisted)
# ─────────────────────────────────────────────
def _run_bot_in_thread(jid, password, recipient, message):
    """
    Crea un event loop propio en el hilo y corre el bot ahí.
    Necesario porque Twisted ya ocupa el hilo principal con su propio loop.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = XMPPNotifierBot(jid, password, recipient, message)
        loop.run_until_complete(bot.run())
        loop.close()
    except asyncio.TimeoutError:
        logger.error("Timeout al intentar enviar la notificación XMPP (15s).")
    except Exception as e:
        logger.error(f"Error inesperado en hilo XMPP: {e}")


# ─────────────────────────────────────────────
# Interfaz pública — llamada desde smtpserver.py
# ─────────────────────────────────────────────
def notify(recipient_jid, message, config_path="config.json"):
    """
    Envía una notificación XMPP en un hilo de background.
    No bloquea el reactor de Twisted.

    Parámetros:
        recipient_jid (str): JID del destinatario.
        message       (str): Texto de la notificación.
        config_path   (str): Ruta a config.json.
    """
    xmpp_config = _load_xmpp_config(config_path)
    if not xmpp_config:
        return

    bot_jid = xmpp_config.get("jid")
    bot_password = xmpp_config.get("password")

    if not bot_jid or not bot_password:
        logger.error("Falta 'jid' o 'password' en la sección 'xmpp' de config.json.")
        return

    thread = threading.Thread(
        target=_run_bot_in_thread,
        args=(bot_jid, bot_password, recipient_jid, message),
        daemon=True,
        name="xmpp-notifier"
    )
    thread.start()
    logger.info(f"Hilo XMPP iniciado para notificar a: {recipient_jid}")


def _load_xmpp_config(config_path):
    if not os.path.exists(config_path):
        logger.error(f"config.json no encontrado: {config_path}")
        return None
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        xmpp_cfg = config.get("xmpp")
        if not xmpp_cfg:
            logger.error("Sección 'xmpp' no encontrada en config.json.")
        return xmpp_cfg
    except Exception as e:
        logger.error(f"Error al leer config.json: {e}")
        return None


# ─────────────────────────────────────────────
# Ejecución independiente para pruebas
# ─────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [XMPP] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Prueba el notificador XMPP de forma independiente."
    )
    parser.add_argument("--to", required=True, help="JID destinatario. Ej: usuario@jabber.fr")
    parser.add_argument("--message", default="Tienes un nuevo correo electrónico.")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    logger.info(f"Enviando notificación XMPP a: {args.to}")
    logger.info(f"Mensaje: {args.message}")

    notify(args.to, args.message, args.config)

    # Espera a que el hilo de background termine
    import time
    time.sleep(20)
    logger.info("Prueba finalizada.")


if __name__ == "__main__":
    main()