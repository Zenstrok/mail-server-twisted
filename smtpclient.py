"""
smtpclient.py - Cliente SMTP para envío masivo y personalizado de correos
Uso: python smtpclient.py -h <mail-server> -c <csv-file> -m <message-file>

Funcionalidades:
  - Lee destinatarios desde un archivo CSV (nombre, email, y columnas extra)
  - Personaliza el mensaje usando variables como {{nombre}}, {{email}}, etc.
  - Soporte completo de MIME (texto plano, HTML y archivos adjuntos)
  - Soporte para conexión SSL/TLS al servidor SMTP
"""

import os
import sys
import csv
import ssl
import json
import smtplib
import logging
import argparse
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────────
# Configuración del logger
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CLIENT] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Procesamiento de la plantilla del mensaje
# ─────────────────────────────────────────────
def render_template(template, variables):
    """
    Reemplaza las variables en la plantilla del mensaje.

    Las variables se definen en el archivo de mensaje con la sintaxis {{nombre_variable}}.
    Las columnas del CSV se pasan como diccionario 'variables'.

    Ejemplo:
        template  = "Hola {{nombre}}, tu correo es {{email}}."
        variables = {"nombre": "Juan", "email": "juan@dominio.com"}
        resultado = "Hola Juan, tu correo es juan@dominio.com."

    Parámetros:
        template  (str): Contenido del archivo de mensaje con variables.
        variables (dict): Diccionario con nombre_variable -> valor (viene del CSV).

    Retorna:
        str: Mensaje con todas las variables reemplazadas.
    """
    rendered = template
    for key, value in variables.items():
        placeholder = "{{" + key.strip() + "}}"
        rendered = rendered.replace(placeholder, str(value).strip())
    return rendered


# ─────────────────────────────────────────────
# Construcción del mensaje MIME
# ─────────────────────────────────────────────
def build_mime_message(sender, recipient_email, subject, body, attachments=None):
    """
    Construye un mensaje MIME completo listo para enviar.

    Si no hay adjuntos, crea un mensaje simple de texto plano.
    Si hay adjuntos, crea un mensaje multipart/mixed con:
      - Parte de texto plano (el cuerpo del mensaje)
      - Una parte por cada archivo adjunto (usando el tipo MIME correcto)

    Parámetros:
        sender         (str): Dirección del remitente. Ej: "yo@dominio.com"
        recipient_email(str): Dirección del destinatario.
        subject        (str): Asunto del correo.
        body           (str): Cuerpo del correo (ya con variables reemplazadas).
        attachments    (list): Lista de rutas a archivos que se adjuntarán.
                               Puede ser None o lista vacía si no hay adjuntos.

    Retorna:
        MIMEMultipart o MIMEText: El objeto de mensaje construido.
    """
    attachments = attachments or []

    if not attachments:
        # Mensaje simple sin adjuntos
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = sender
        msg["To"] = recipient_email
        msg["Subject"] = subject
        return msg

    # Mensaje con adjuntos: estructura multipart/mixed
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = recipient_email
    msg["Subject"] = subject

    # Parte de texto (el cuerpo del mensaje)
    text_part = MIMEText(body, "plain", "utf-8")
    msg.attach(text_part)

    # Adjuntar cada archivo
    for filepath in attachments:
        filepath = filepath.strip()
        if not os.path.exists(filepath):
            logger.warning(f"Adjunto no encontrado, se omite: {filepath}")
            continue

        # Detectar el tipo MIME del archivo automáticamente
        mime_type, _ = mimetypes.guess_type(filepath)
        if mime_type is None:
            mime_type = "application/octet-stream"

        main_type, sub_type = mime_type.split("/", 1)

        try:
            with open(filepath, "rb") as f:
                file_data = f.read()

            # Crear la parte MIME para el adjunto
            attachment_part = MIMEBase(main_type, sub_type)
            attachment_part.set_payload(file_data)
            encoders.encode_base64(attachment_part)

            filename = os.path.basename(filepath)
            attachment_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=filename
            )
            attachment_part.add_header(
                "Content-Type",
                mime_type,
                name=filename
            )

            msg.attach(attachment_part)
            logger.info(f"Adjunto agregado: {filename} ({mime_type})")

        except Exception as e:
            logger.error(f"Error al adjuntar {filepath}: {e}")

    return msg


# ─────────────────────────────────────────────
# Envío de un correo individual
# ─────────────────────────────────────────────
def send_email(server_host, server_port, sender, recipient_email,
               subject, body, attachments=None, use_ssl=False):
    """
    Envía un correo electrónico a un destinatario.

    Parámetros:
        server_host    (str) : Hostname o IP del servidor SMTP.
        server_port    (int) : Puerto del servidor SMTP.
        sender         (str) : Dirección del remitente.
        recipient_email(str) : Dirección del destinatario.
        subject        (str) : Asunto del correo.
        body           (str) : Cuerpo del correo (ya personalizado).
        attachments    (list): Lista de rutas de archivos a adjuntar.
        use_ssl        (bool): Si True, usa SSL directo (SMTPS). Si False, usa SMTP plano.

    Retorna:
        bool: True si el envío fue exitoso, False si hubo error.
    """
    msg = build_mime_message(sender, recipient_email, subject, body, attachments)

    try:
        if use_ssl:
            # Conexión directa SSL (puerto típico 465)
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE  # Para certificados autofirmados
            with smtplib.SMTP_SSL(server_host, server_port, context=ssl_context) as server:
                server.set_debuglevel(0)
                server.sendmail(sender, recipient_email, msg.as_string())
                logger.info(f"[SSL] Correo enviado a: {recipient_email}")
        else:
            # Conexión SMTP plana (puerto 2525 o 25)
            with smtplib.SMTP(server_host, server_port) as server:
                server.set_debuglevel(0)
                server.sendmail(sender, recipient_email, msg.as_string())
                logger.info(f"Correo enviado a: {recipient_email}")

        return True

    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Destinatario rechazado por el servidor: {recipient_email} - {e}")
    except smtplib.SMTPConnectError as e:
        logger.error(f"No se pudo conectar al servidor {server_host}:{server_port} - {e}")
    except smtplib.SMTPException as e:
        logger.error(f"Error SMTP al enviar a {recipient_email}: {e}")
    except Exception as e:
        logger.error(f"Error inesperado al enviar a {recipient_email}: {e}")

    return False


# ─────────────────────────────────────────────
# Lectura del CSV de destinatarios
# ─────────────────────────────────────────────
def read_recipients_csv(csv_path):
    """
    Lee el archivo CSV de destinatarios.

    El CSV debe tener al menos las columnas 'nombre' y 'email'.
    Puede tener columnas adicionales que también serán usadas como variables
    para personalizar el mensaje (ej: ciudad, empresa, etc.)

    Formato esperado del CSV:
        nombre,email,ciudad
        Juan Pérez,juan@dominio.com,San José
        María López,maria@otro.com,Heredia

    Parámetros:
        csv_path (str): Ruta al archivo CSV.

    Retorna:
        list[dict]: Lista de diccionarios, uno por destinatario.

    Lanza:
        SystemExit si el archivo no existe o no tiene las columnas requeridas.
    """
    if not os.path.exists(csv_path):
        logger.error(f"Archivo CSV no encontrado: {csv_path}")
        sys.exit(1)

    recipients = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            # Verifica que existan las columnas mínimas requeridas
            if reader.fieldnames is None:
                logger.error("El CSV está vacío o mal formateado.")
                sys.exit(1)

            fieldnames_lower = [fn.strip().lower() for fn in reader.fieldnames]
            if "nombre" not in fieldnames_lower or "email" not in fieldnames_lower:
                logger.error(
                    f"El CSV debe tener columnas 'nombre' y 'email'. "
                    f"Columnas encontradas: {reader.fieldnames}"
                )
                sys.exit(1)

            for i, row in enumerate(reader, start=2):
                # Normaliza las claves a minúsculas
                row_normalized = {k.strip().lower(): v for k, v in row.items()}
                if not row_normalized.get("email", "").strip():
                    logger.warning(f"Fila {i}: campo 'email' vacío, se omite.")
                    continue
                recipients.append(row_normalized)

    except Exception as e:
        logger.error(f"Error al leer el CSV: {e}")
        sys.exit(1)

    logger.info(f"Total de destinatarios leídos: {len(recipients)}")
    return recipients


# ─────────────────────────────────────────────
# Lectura del archivo de mensaje
# ─────────────────────────────────────────────
def read_message_file(message_path):
    """
    Lee el archivo de mensaje que contiene el asunto y el cuerpo del correo.

    Formato esperado del archivo de mensaje:
        Subject: Aquí va el asunto del correo
        Attachments: ruta/a/archivo1.pdf, ruta/a/archivo2.jpg  (opcional)

        Cuerpo del mensaje aquí.
        Hola {{nombre}}, tu correo es {{email}}.
        Puedes usar cualquier columna del CSV como variable.

    La primera línea que comience con "Subject:" define el asunto.
    La línea que comience con "Attachments:" lista archivos a adjuntar separados por comas.
    El resto (después de la primera línea en blanco) es el cuerpo.

    Parámetros:
        message_path (str): Ruta al archivo de mensaje.

    Retorna:
        tuple: (subject: str, body: str, attachments: list)
    """
    if not os.path.exists(message_path):
        logger.error(f"Archivo de mensaje no encontrado: {message_path}")
        sys.exit(1)

    subject = "Sin asunto"
    attachments = []
    body_lines = []
    header_section = True

    try:
        with open(message_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            stripped = line.rstrip("\n")

            # Línea en blanco separa cabeceras del cuerpo
            if header_section and stripped.strip() == "":
                header_section = False
                continue

            if header_section:
                if stripped.lower().startswith("subject:"):
                    subject = stripped[len("subject:"):].strip()
                elif stripped.lower().startswith("attachments:"):
                    raw_attachments = stripped[len("attachments:"):].strip()
                    attachments = [a.strip() for a in raw_attachments.split(",") if a.strip()]
                # Otras cabeceras se ignoran silenciosamente
            else:
                body_lines.append(stripped)

        body = "\n".join(body_lines)

    except Exception as e:
        logger.error(f"Error al leer el archivo de mensaje: {e}")
        sys.exit(1)

    logger.info(f"Asunto: '{subject}'")
    if attachments:
        logger.info(f"Adjuntos definidos en mensaje: {attachments}")

    return subject, body, attachments


# ─────────────────────────────────────────────
# Punto de entrada principal
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description=(
            "Cliente SMTP para envío masivo y personalizado de correos. "
            "Lee destinatarios de un CSV y personaliza el mensaje con variables."
        )
    )
    parser.add_argument(
        "-h_server", "--host",
        required=True,
        dest="host",
        help="Hostname o IP del servidor SMTP. Ejemplo: -h localhost"
    )
    parser.add_argument(
        "-c", "--csv",
        required=True,
        help="Ruta al archivo CSV con destinatarios. Columnas requeridas: nombre, email."
    )
    parser.add_argument(
        "-m", "--message",
        required=True,
        help="Ruta al archivo de mensaje. Debe incluir Subject: en la primera línea."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2525,
        help="Puerto del servidor SMTP (default: 2525)"
    )
    parser.add_argument(
        "--sender",
        default="remitente@servidor.com",
        help="Dirección del remitente (default: remitente@servidor.com)"
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        help="Usar conexión SSL directa al servidor SMTP (SMTPS)"
    )

    args = parser.parse_args()

    # Lee el archivo de mensaje (asunto, cuerpo, adjuntos)
    subject_template, body_template, attachments = read_message_file(args.message)

    # Lee la lista de destinatarios del CSV
    recipients = read_recipients_csv(args.csv)

    if not recipients:
        logger.error("No hay destinatarios válidos en el CSV. Abortando.")
        sys.exit(1)

    # Contadores para el resumen final
    sent_count = 0
    failed_count = 0

    logger.info(f"Iniciando envío a {len(recipients)} destinatario(s)...")
    logger.info(f"Servidor: {args.host}:{args.port} | SSL: {args.ssl}")

    for recipient in recipients:
        email_address = recipient.get("email", "").strip()
        if not email_address:
            logger.warning("Registro sin email, se omite.")
            failed_count += 1
            continue

        # Personaliza el asunto y cuerpo con las variables del CSV
        # Cualquier columna del CSV puede usarse como {{nombre_columna}}
        personalized_subject = render_template(subject_template, recipient)
        personalized_body = render_template(body_template, recipient)

        logger.info(f"Enviando a: {email_address} (nombre: {recipient.get('nombre', 'N/A')})")

        success = send_email(
            server_host=args.host,
            server_port=args.port,
            sender=args.sender,
            recipient_email=email_address,
            subject=personalized_subject,
            body=personalized_body,
            attachments=attachments,
            use_ssl=args.ssl
        )

        if success:
            sent_count += 1
        else:
            failed_count += 1

    # Resumen final
    logger.info("─" * 50)
    logger.info(f"Envío completado.")
    logger.info(f"  Enviados exitosamente : {sent_count}")
    logger.info(f"  Fallidos              : {failed_count}")
    logger.info(f"  Total procesados      : {sent_count + failed_count}")


if __name__ == "__main__":
    main()
