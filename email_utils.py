import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib
from jinja2 import Environment, FileSystemLoader

# Настройки SMTP (MailHog)
SMTP_HOST = "127.0.0.1"
SMTP_PORT = 1025
SMTP_USERNAME = None   # MailHog не требует аутентификации
SMTP_PASSWORD = None

# Папка с шаблонами писем (можно использовать те же templates)
TEMPLATE_DIR = "templates/emails"

# Среда Jinja2 для писем
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

async def send_email(recipient: str, subject: str, body_html: str):
    message = MIMEMultipart("alternative")
    message["From"] = "noreply@accelerator.local"
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(body_html, "html", "utf-8"))

    await aiosmtplib.send(
        message,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USERNAME,
        password=SMTP_PASSWORD,
        use_tls=False,          # локально без шифрования
    )

async def send_response_notification(request_title: str, recipient_email: str, sender_name: str, message_text: str):
    template = env.get_template("response_notification.html")
    body = template.render(
        request_title=request_title,
        sender_name=sender_name,
        message_text=message_text
    )
    subject = f"Новый отклик на заявку «{request_title}»"
    await send_email(recipient_email, subject, body)

async def send_confirmation_email(recipient_email: str, user_name: str, token: str):
    confirm_url = f"http://127.0.0.1:8000/confirm/{token}"  # в будущем заменить на реальный домен
    template = env.get_template("confirm_email.html")
    body = template.render(user_name=user_name, confirm_url=confirm_url)
    subject = "Подтверждение регистрации"
    await send_email(recipient_email, subject, body)

async def send_reset_password_email(recipient_email: str, user_name: str, token: str):
    reset_url = f"http://127.0.0.1:8000/reset-password/{token}"
    template = env.get_template("reset_password_email.html")
    body = template.render(user_name=user_name, reset_url=reset_url)
    subject = "Восстановление пароля"
    await send_email(recipient_email, subject, body)

async def send_review_invitation(recipient_email: str, expert_name: str, project_title: str, project_description: str, review_url: str):
    template = env.get_template("review_invitation.html")
    body = template.render(
        expert_name=expert_name,
        project_title=project_title,
        project_description=project_description,
        review_url=review_url
    )
    subject = f"Приглашение на оценку проекта «{project_title}»"
    await send_email(recipient_email, subject, body)

async def send_review_result(startup_email: str, startup_name: str, project_title: str, overall_score: float, comments: list):
    template = env.get_template("review_result.html")
    body = template.render(
        startup_name=startup_name,
        project_title=project_title,
        overall_score=overall_score,
        comments=comments
    )
    status_text = "принят" if overall_score >= 3 else "отклонён"
    subject = f"Результат оценки проекта «{project_title}»: {status_text}"
    await send_email(startup_email, subject, body)