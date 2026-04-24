# Documentación: Tarea e-Mail
**Curso:** Redes — Ingeniería de Computación

**Profesor:** Kevin Moraga

**Estudiante:** Jose Mario Jiménez Vargas

**Carné:** 2023102334

**Fecha:** 21 de abril, 2026

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Ambiente de Desarrollo](#2-ambiente-de-desarrollo)
3. [Estructuras de Datos y Funciones](#3-estructuras-de-datos-y-funciones)
4. [Instrucciones para Ejecutar el Programa](#4-instrucciones-para-ejecutar-el-programa)
5. [Actividades Realizadas por Estudiante](#5-actividades-realizadas-por-estudiante)
6. [Autoevaluación](#6-autoevaluación)
7. [Lecciones Aprendidas](#7-lecciones-aprendidas)
8. [Bibliografía](#8-bibliografía)

---

## 1. Introducción

El objetivo de esta tarea es implementar desde cero, utilizando Python con la biblioteca
Twisted, un sistema completo de correo electrónico compuesto por cuatro componentes:

- **SMTP Server:** Recibe y almacena correos entrantes, valida dominios, soporta adjuntos MIME y cifrado TLS.
- **SMTP Client:** Envía correos masivos personalizados leyendo destinatarios desde un CSV.
- **POP3 Server:** Permite a clientes de correo como Thunderbird descargar y leer mensajes.
- **XMPP Notifier:** Notifica al usuario vía mensajería instantánea cuando llega un correo nuevo.

### Arquitectura del sistema

```
                         ┌──────────────────────┐
                         │    smtpserver.py     │
  [Remitente / cliente]  │  Puerto 2525 (TCP)   │
  ──────── SMTP ────────>│  Puerto 4650 (SSL)   │──guarda .eml──> mailstorage/
                         │                      │                  mariojimenez@
                         └──────────┬───────────┘                 mariojimenez.tech/
                                    │ llama notify()
                                    ▼
                         ┌─────────────────────┐       ┌──────────────────────┐
                         │   xmpp_notifier.py  │─XMPP─>│  Gajim / cliente     │
                         │   (bot slixmpp)     │       │  XMPP del usuario    │
                         └─────────────────────┘       └──────────────────────┘

  [destinatarios.csv]    ┌──────────────────────┐
  [mensaje.txt]          │    smtpclient.py     │──SMTP──> smtpserver.py
  ──────────────────────>│  (envío masivo)      │
                         └──────────────────────┘

                         ┌──────────────────────┐
  [Thunderbird /         │    pop3server.py     │
   cliente POP3] <──────>│  Puerto 1100 (TCP)   │<──lee── mailstorage/
                         │  Puerto 9950 (SSL)   │
                         └──────────────────────┘
```

El flujo completo de un correo es entonces: el smtpclient.py lee el CSV de
destinatarios, personaliza el mensaje con las variables definidas, y lo envía al
smtpserver.py por SMTP. El servidor valida que el dominio del destinatario
esté en la lista de dominios aceptados, almacena el correo como archivo .eml en
la carpeta del usuario, y notifica al usuario vía XMPP. Posteriormente, el usuario
puede conectar Thunderbird al pop3server.py para descargar y leer sus mensajes.

---

## 2. Ambiente de Desarrollo

### Sistema operativo y lenguaje

| Componente | Herramienta | Versión |
|---|---|---|
| Sistema Operativo | Ubuntu | — |
| Lenguaje | Python | 3.12 |
| Entorno virtual | venv | — |
| Framework | Twisted | última estable |
| Soporte SSL/TLS | PyOpenSSL + service_identity | última estable |
| Cliente XMPP | slixmpp / Gajim | última estable |
| Generación de certificados | OpenSSL CLI | — |

### Instalación del entorno virtual y dependencias

```bash
# Crear el entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install twisted pyopenssl service_identity slixmpp
```

### Herramientas de desarrollo y debugging

| Herramienta | Uso |
|---|---|
| VS Code | Editor de codigo |
| telnet | Prueba manual de comandos SMTP y POP3 |
| openssl s_client | Prueba de conexiones SSL/TLS |
| Thunderbird | Cliente de correo para verificar POP3 |
| Gajim | Cliente XMPP para recibir notificaciones |
| Git + GitHub | Control de versiones |

### Simulación local del dominio

Para desarrollar y probar sin necesitar DNS real, se agregó una entrada en
`/etc/hosts`:

```
127.0.0.1   mariojimenez.tech
```

Esto permite que todos los comandos usen el dominio real `mariojimenez.tech`
aunque resuelvan localmente a `127.0.0.1`.

---

## 3. Estructuras de Datos y Funciones

---

### 3.1 `smtpserver.py`

#### Estructura de almacenamiento en disco

Los correos se almacenan en el sistema de archivos siguiendo esta jerarquía:

```
mailstorage/
└── mariojimenez@mariojimenez.tech/
    ├── 20260421_220000_123456.eml
    ├── 20260421_223015_789012.eml
    └── ...
```

Cada archivo `.eml` es el correo completo en formato RFC, incluyendo
cabeceras, cuerpo y adjuntos MIME codificados en base64. El nombre del archivo
es un timestamp con microsegundos para garantizar unicidad.

#### Clase `MailMessage`

Acumula las líneas del correo durante la recepción SMTP y lo escribe a disco al finalizar.

| Atributo / Método | Tipo | Descripción |
|---|---|---|
| `recipient_address` | `str` | Dirección completa del destinatario |
| `mail_storage` | `str` | Ruta base de almacenamiento |
| `sender_address` | `str` | Dirección del remitente (para la notificación XMPP) |
| `lines` | `list[bytes]` | Acumula cada línea recibida del cliente SMTP |
| `lineReceived(line)` | método | Agrega una línea a `self.lines` |
| `eomReceived()` | método | Fin del mensaje: escribe el `.eml` y notifica XMPP |
| `connectionLost()` | método | Limpia si la conexión se pierde antes de terminar |

#### Clase `MailDelivery`

Implementa la interfaz `IMessageDelivery` de Twisted. Twisted la consulta en cada
paso del protocolo SMTP para decidir qué aceptar o rechazar.

| Método | Descripción |
|---|---|
| `receivedHeader(helo, origin, recipients)` | Genera la cabecera `Received:` del mensaje |
| `validateFrom(helo, origin)` | Valida el remitente. Este servidor acepta cualquier origen |
| `validateTo(user)` | Valida el destinatario. Rechaza con `SMTPBadRcpt` si el dominio no está en la lista de aceptados |

La validación de dominio en `validateTo` funciona así:

```python
address = str(user.dest)           # "mario@mariojimenez.tech"
domain = address.split("@")[-1]    # "mariojimenez.tech"
if domain in self.domains:         # ["mariojimenez.tech"]
    return lambda: MailMessage(...)
raise smtp.SMTPBadRcpt(user)       # Rechaza
```

#### Clase `CustomSMTPFactory`

Hereda de `smtp.SMTPFactory`. Su único rol es construir una instancia del protocolo
SMTP por cada conexión entrante e inyectarle un `MailDelivery` fresco.

#### Función `notify_xmpp(recipient_user, sender_address)`

Carga `config.json`, obtiene el `xmpp_jid` del usuario e invoca `xmpp_notifier.notify()`.
Maneja silenciosamente el caso donde slixmpp no esté instalado o el usuario no
tenga XMPP configurado.

---

### 3.2 `smtpclient.py`

#### Estructura del archivo de mensaje

```
Subject: Hola {{nombre}}, bienvenido
Attachments: docs/archivo1.pdf, docs/archivo2.jpg

Estimado/a {{nombre}},

Tu correo registrado es {{email}}.
Cualquier columna del CSV puede usarse como {{nombre_columna}}.
```

La primera sección (antes de la línea en blanco) son cabeceras. El resto es el cuerpo.

#### Función `render_template(template, variables)`

Reemplaza marcadores `{{variable}}` con los valores del diccionario `variables`.
Las claves del diccionario corresponden a los nombres de columnas del CSV en minúsculas.

```python
# Ejemplo de uso
template  = "Hola {{nombre}}, tu correo es {{email}}."
variables = {"nombre": "Juan Pérez", "email": "juan@dominio.com"}
resultado = "Hola Juan Pérez, tu correo es juan@dominio.com."
```

#### Función `build_mime_message(sender, recipient_email, subject, body, attachments)`

Construye el objeto `MIMEMultipart` o `MIMEText` según si hay adjuntos o no.

| Caso | Estructura MIME resultante |
|---|---|
| Sin adjuntos | `MIMEText` (text/plain, UTF-8) |
| Con adjuntos | `MIMEMultipart("mixed")` con una parte `MIMEText` + una parte `MIMEBase` por cada adjunto |

Para cada adjunto:
1. Detecta el tipo MIME automáticamente con `mimetypes.guess_type(filepath)`.
2. Si no puede detectarlo, usa `application/octet-stream`.
3. Codifica el contenido en base64 con `encoders.encode_base64(part)`.
4. Agrega la cabecera `Content-Disposition: attachment; filename="..."`.

#### Función `read_recipients_csv(csv_path)`

Lee el CSV y retorna una lista de diccionarios con las columnas normalizadas a
minúsculas. Verifica que existan las columnas obligatorias `nombre` y `email`.
Omite filas con email vacío emitiendo una advertencia.

#### Función `send_email(..., use_ssl=False)`

Envía el correo usando `smtplib.SMTP` (plano) o `smtplib.SMTP_SSL` (SSL directo).
Para certificados autofirmados en desarrollo, deshabilita la verificación con
`ssl_context.verify_mode = ssl.CERT_NONE`.

---

### 3.3 `pop3server.py`

#### Clase `SimpleMailbox`

Implementa `IMailbox` de Twisted. Representa el buzón de un usuario en disco.

| Atributo / Método | Descripción |
|---|---|
| `messages` | Lista ordenada de rutas absolutas a archivos `.eml` del usuario |
| `_deleted` | `set` de índices marcados para eliminación |
| `listMessages(index)` | Retorna tamaño(s) en bytes. Mensajes marcados retornan 0 |
| `getMessage(index)` | Retorna el archivo `.eml` abierto en modo binario |
| `getUidl(index)` | Retorna el nombre del archivo como identificador único |
| `deleteMessage(index)` | Agrega `index` a `_deleted` (no borra el archivo todavía) |
| `undeleteMessages()` | Limpia `_deleted` (implementa comando RSET) |
| `sync()` | Borra físicamente los archivos en `_deleted` y limpia el set |
| `getMessageCount()` | `len(messages) - len(_deleted)` |
| `getMailboxSize()` | Suma de bytes de mensajes no eliminados |

La eliminación diferida (marcar → borrar en `sync`) es el comportamiento estándar
de POP3: los mensajes se eliminan del servidor solo cuando el cliente cierra la
sesión limpiamente con `QUIT`.

#### Clase `MailRealm`

Implementa el realm de Twisted Cred para POP3. Su método `requestAvatar` recibe
el `avatarId` (nombre de usuario ya autenticado) y retorna la tupla
`(IMailbox, SimpleMailbox, logout_fn)` que Twisted espera.

Busca la carpeta del usuario probando `usuario@dominio` para cada dominio de la
lista. Si no existe ninguna, la crea con el primer dominio configurado.

#### Clase `ConfigFileChecker`

Implementa `ICredentialsChecker` de Twisted Cred. Lee `config.json` en cada
llamada a `requestAvatarId` para verificar usuario y contraseña. Si las
credenciales son incorrectas, retorna un `Deferred` fallido con
`credError.UnauthorizedLogin`.

#### Clase `POP3Factory`

Factory manual que reemplaza el `pop3.POP3Factory` eliminado en versiones modernas
de Twisted. Hereda de `ServerFactory` y en `buildProtocol` crea una instancia de
`pop3.POP3` inyectándole el portal de autenticación.

```python
class POP3Factory(ServerFactory):
    protocol = pop3.POP3

    def buildProtocol(self, addr):
        p = self.protocol()
        p.portal = self.portal   # Inyección del portal
        p.factory = self
        return p
```

---

### 3.4 `xmpp_notifier.py`

#### Clase `XMPPNotifierBot`

Bot XMPP asíncrono basado en slixmpp. Al conectarse exitosamente al servidor XMPP,
envía el mensaje de notificación y se desconecta.

| Método | Descripción |
|---|---|
| `__init__(jid, password, recipient, message)` | Inicializa las credenciales y datos del mensaje |
| `run()` | Corrutina asyncio: conecta, envía, desconecta |

El flujo interno de `run()`:

1. Crea el cliente `slixmpp.ClientXMPP`.
2. Registra handlers para `session_start`, `failed_auth` y `disconnected`.
3. Llama a `client.connect()`.
4. Espera con `asyncio.wait_for(done.wait(), timeout=15)` hasta que el handler de `session_start` termine o hasta 15 segundos.
5. En `session_start`: envía presencia, obtiene roster, envía el mensaje, desconecta.

#### Función `_run_bot_in_thread(jid, password, recipient, message)`

Crea un event loop de asyncio independiente con `asyncio.new_event_loop()` y corre
el bot en él. Necesario para no interferir con el reactor de Twisted que corre en
el hilo principal.

#### Función `notify(recipient_jid, message, config_path)`

Interfaz pública del módulo. Carga las credenciales del bot desde `config.json` y
lanza `_run_bot_in_thread` en un hilo daemon con `threading.Thread`. No bloquea.

---

### 3.5 `config.json`

Archivo de configuración central del sistema. Es leído por `smtpserver.py`,
`pop3server.py` y `xmpp_notifier.py`.

```json
{
    "domains": ["mariojimenez.tech"],
    "users": {
        "mariojimenez": {
            "password": "jjimenez217",
            "xmpp_jid": "mariojimenez@jabber.fr"
        }
    },
    "xmpp": {
        "jid": "notificador.mariojimenez@jabber.fr",
        "password": "contraseña_bot"
    }
}
```

| Clave | Descripción |
|---|---|
| `domains` | Lista de dominios que el SMTP server acepta como destino |
| `users` | Diccionario de usuarios del sistema. La clave es el nombre de usuario |
| `users.X.password` | Contraseña para autenticarse en el POP3 server |
| `users.X.xmpp_jid` | JID de XMPP del usuario para recibir notificaciones |
| `xmpp.jid` | JID del bot notificador que envía los mensajes XMPP |
| `xmpp.password` | Contraseña del bot en el servidor XMPP |

---

## 4. Instrucciones para Ejecutar el Programa

### 4.1 Requisitos

```bash
# Activar el entorno virtual
source venv/bin/activate

# Verificar que las dependencias están instaladas
pip install twisted pyopenssl service_identity slixmpp

# Generar certificados SSL autofirmados (solo la primera vez)
mkdir -p certs
openssl req -newkey rsa:2048 -nodes \
    -keyout certs/server.key \
    -x509 -days 365 \
    -out certs/server.crt

# Agregar el dominio al /etc/hosts para pruebas locales
echo "127.0.0.1   mariojimenez.tech" | sudo tee -a /etc/hosts
```

### 4.2 Iniciar el SMTP Server

En una terminal dedicada para el servidor SMTP:

```bash
python smtpserver.py -d mariojimenez.tech -s ./mailstorage -p 2525
```

### 4.3 Iniciar el POP3 Server

En otra terminal:

```bash
python pop3server.py -s ./mailstorage -p 1100 -d mariojimenez.tech
```

### 4.4 Enviar correos con el SMTP Client

#### Preparar los archivos de entrada

**`destinatarios.csv`:**
```csv
nombre,email
Mario Jiménez,mariojimenez@mariojimenez.tech
Juan Pérez,mariojimenez@mariojimenez.tech
```

**`mensaje.txt`:**
```
Subject: Hola {{nombre}}, mensaje de prueba
Attachments: docs/prueba.pdf

Estimado/a {{nombre}},

Este es un correo de prueba enviado desde el cliente SMTP.
Tu dirección de correo es: {{email}}

Saludos,
El servidor de prueba
```

#### Ejecutar el cliente

```bash
python smtpclient.py --host mariojimenez.tech \
                     -c destinatarios.csv \
                     -m mensaje.txt \
                     --port 2525 \
                     --sender remitente@mariojimenez.tech
```

#### Verificar que los correos llegaron al servidor

Se busca en la carpeta mailstorage el correo enviado.

### 4.5 Probar SMTP manualmente con telnet

Es útil para demostrar el protocolo SMTP paso a paso:

```bash
telnet localhost 2525
```

Luego escribir los comandos uno por uno:

```
220 ... ESMTP Twisted
HELO mariojimenez.tech
250 ... Hello
MAIL FROM:<remitente@mariojimenez.tech>
250 Sender address accepted
RCPT TO:<mariojimenez@mariojimenez.tech>
250 Recipient address accepted
DATA
354 Continue
Subject: Prueba telnet
From: remitente@mariojimenez.tech
To: mariojimenez@mariojimenez.tech

Hola, este es un correo enviado manualmente con telnet.
.
250 Delivery in progress
QUIT
221 See you later
```

### 4.6 Probar SMTP con SSL usando openssl

```bash
openssl s_client -connect localhost:4650
```
Una vez conectado, los comandos son idénticos a los de telnet.

### 4.7 Probar el XMPP Notifier

```bash
python xmpp_notifier.py \
    --to mariojimenez@jabber.fr \
    --message "Tienes un nuevo correo electrónico de prueba"
```

La notificación debe aparecer en el cliente Gajim conectado con la cuenta `mariojimenez@jabber.fr`.

### 4.8 Configurar Thunderbird para leer correos vía POP3

Con el POP3 server corriendo, configurar Thunderbird así:

1. Abrir Thunderbird → **Configuración de cuentas** → **Agregar cuenta de correo**.
2. Ingresar nombre, correo (`mariojimenez@mariojimenez.tech`) y contraseña (`jjimenez217`).
3. Cuando Thunderbird intente autodetectar, cancelar y configurar manualmente.
4. Configurar el servidor entrante:

| Campo | Valor |
|---|---|
| Protocolo | POP3 |
| Servidor | localhost |
| Puerto | 1100 |
| Seguridad | Ninguna |
| Autenticación | Contraseña normal |

5. Si Thunderbird muestra advertencia de seguridad, confirmar la excepción.
6. Hacer clic en **Obtener mensajes**. Los correos recibidos deben aparecer en la bandeja.
7. Verificar que después de descargar, los archivos `.eml` son eliminados del servidor:

```bash
ls mailstorage/mariojimenez@mariojimenez.tech/
# Debe estar vacío después de que Thunderbird descargó y cerró la sesión
```

### 4.9 Probar POP3 manualmente con telnet

```bash
telnet localhost 1100
```

```
+OK Twisted POP3 server
USER mariojimenez
+OK
PASS jjimenez217
+OK Mailbox locked and ready
STAT
+OK 2 1234
LIST
+OK
1 612
2 734
.
RETR 1
+OK 612 octets
... (contenido del correo) ...
.
DELE 1
+OK Deleted
QUIT
+OK
```

---

## 5. Actividades Realizadas por Estudiante

| Fecha | Actividad | Horas |
|---|---|---|
| 17/04/2026 | Lectura del enunciado, investigación de Twisted mail y arquitectura general, generacion Kick-off | 1.5 |
| 18/04/2026 | Configuración del entorno virtual, instalación de dependencias, generación de certificados SSL | 0.5 |
| 18/04/2026 | Implementación inicial de `smtpserver.py`: clases `MailMessage` y `MailDelivery` | 2.0 |
| 18/04/2026 | Implementación de `smtpclient.py`: lectura de CSV, plantillas con variables, MIME | 2.0 |
| 20/04/2026 | Implementación inicial de `pop3server.py` con Twisted Cred | 2.0 |
| 20/04/2026 | Pruebas de POP3 con telnet y verificación de eliminación de mensajes en `sync()` | 1.0 |
| 20/04/2026 | Implementación de `xmpp_notifier.py`, investigación de slixmpp asyncio | 2.5 |
| 21/04/2026 | Integración del notificador XMPP con el SMTP server (`notify_xmpp` en `eomReceived`) | 1.0 |
| 21/04/2026 | Configuración de Thunderbird, pruebas de flujo completo | 2.0 |
| 21/04/2026 | Configuración de `/etc/hosts` para simulación local del dominio | 0.5 |
| 21/04/2026 | Redacción de la documentación | 3.0 |
| **Total** | | **18.0 h** |

---

## 6. Autoevaluación

### Estado final del programa

El sistema fue implementado en su totalidad. Todos los componentes obligatorios
funcionan correctamente:

- El **SMTP Server** recibe correos, valida dominios, almacena los `.eml` y notifica por XMPP.
- El **SMTP Client** lee el CSV, personaliza el mensaje con variables y envía incluyendo adjuntos MIME.
- El **POP3 Server** autentica usuarios, entrega correos a Thunderbird y los elimina tras la descarga.
- El **XMPP Notifier** corre en un hilo separado y envía la notificación sin bloquear el servidor.
- **SSL/TLS** está habilitado en puertos separados para tanto SMTP como POP3.

### Problemas encontrados y cómo se resolvieron

**1. No se hace entrega del dominio hacia mi persona, por parte de los hosts**
Los hosts de dominios no me entregaron un dominio a tiempo, por lo que modifique el archivo hosts en la pc para que se pueda resolver el dominio que se supone que me iban a dar.

**2. process() eliminado en slixmpp moderno**
Al intentar usar el notificador XMPP, devolvia 'ClientXMPP' object has no attribute 'process'. slixmpp migró a una funcionalidad que se llama asyncio puro y eliminó process(). Se resolvió reescribiendo XMPPNotifierBot como un asyncio con un asyncio.Event.

### Limitaciones adicionales

- El SMTP server no tiene autenticación SMTP (SMTP AUTH). Cualquier cliente puede enviar correos siempre que el dominio destino sea aceptado. Para un entorno de producción sería bueno agregar autenticación.
- El POP3 server almacena las contraseñas en texto plano en `config.json`. En producción se deberían hashear.

### Reporte de commits de Git

Se me fue hacer commits al repositorio, por lo que solo hay un commit con la tarea completada.

### Rúbrica de autoevaluación

| Componente | Puntaje asignado (0-10) |
|---|---|
| kick-off | 10 |
| smtp-server | 10 |
| smtp-client | 10 |
| pop3-server | 10 |
| xmpp-notifier | 10 | 
| Modo SSL pop3 y smtp-server | 10 | 
| smtp-server en dominio | 8 | 
| Documentación | 10 | 

---

## 7. Lecciones Aprendidas

**1. Twisted es poderoso pero su documentación está complicada.**
Gran parte de los ejemplos en Internet usan APIs que fueron removidas en versiones
modernas. Antes de implementar cualquier componente con Twisted, hay que verificar en el
código fuente del paquete instalado qué clases y métodos existen realmente..

**2. Probar cada componente aislado antes de integrar.**
El flujo SMTP, almacenamiento, POP3, XMPP tiene cuatro puntos de falla
independientes. Si se intenta probar todo junto desde el principio, cuando algo
falla no se sabe dónde está el problema.

**3. /etc/hosts es muy bueno para desarrollo local.**
No se necesita un dominio real ni una VPS para desarrollar y demostrar que el
sistema funciona. Agregar `127.0.0.1 tudominio.tech` a `/etc/hosts` permite
usar el dominio real en todos los comandos y configuraciones mientras se trabaja
en local.

---

## 8. Bibliografía

- Twisted Project. (2024). *Twisted Documentation*. https://docs.twistedmatrix.com/en/stable/
- Twisted Project. (2024). *twisted.mail API Reference*. https://docs.twistedmatrix.com/en/stable/api/twisted.mail.html
- slixmpp Project. (2024). *slixmpp Documentation*. https://slixmpp.readthedocs.io/
- Klensin, J. (2008). *RFC 5321 - Simple Mail Transfer Protocol*. IETF. https://datatracker.ietf.org/doc/html/rfc5321
- Myers, J., & Rose, M. (1996). *RFC 1939 - Post Office Protocol - Version 3*. IETF. https://datatracker.ietf.org/doc/html/rfc1939
- Saint-Andre, P. (2011). *RFC 6120 - Extensible Messaging and Presence Protocol (XMPP)*. IETF. https://datatracker.ietf.org/doc/html/rfc6120
- Freed, N., & Borenstein, N. (1996). *RFC 2045 - Multipurpose Internet Mail Extensions (MIME) Part One*. IETF. https://datatracker.ietf.org/doc/html/rfc2045
- Python Software Foundation. (2024). *smtplib — SMTP protocol client*. https://docs.python.org/3/library/smtplib.html
- Python Software Foundation. (2024). *email — An email and MIME handling package*. https://docs.python.org/3/library/email.html
- Python Software Foundation. (2024). *asyncio — Asynchronous I/O*. https://docs.python.org/3/library/asyncio.html
- OpenSSL Project. (2024). *OpenSSL Documentation*. https://www.openssl.org/docs/
- Mozilla Foundation. (2024). *Thunderbird — Configure POP3 Account*. https://support.mozilla.org/en-US/kb/thunderbird-imap-pop3