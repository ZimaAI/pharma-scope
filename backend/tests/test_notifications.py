import asyncio

from backend.notifications import SMTPAdapter


def test_smtp_is_disabled_by_default():
    result = asyncio.run(SMTPAdapter(enabled=False).send(recipient="user@example.invalid", subject="x", body="y"))
    assert result.state == "disabled" and result.error_code == "smtp_disabled"


def test_smtp_dry_run_never_opens_socket():
    result = asyncio.run(SMTPAdapter(host="smtp.invalid", sender="noreply@example.invalid", enabled=True, dry_run=True).send(recipient="user@example.invalid", subject="x", body="y", idempotency_key="d1"))
    assert result.state == "dry_run" and result.message_id == "d1"


def test_smtp_retry_preserves_message_id_and_reports_exhaustion(monkeypatch):
    import smtplib
    adapter=SMTPAdapter(host='smtp.invalid',sender='sender@example.invalid',enabled=True,dry_run=False,retries=3)
    attempts=[]
    def failing(message):
        attempts.append(message['Message-ID'])
        raise smtplib.SMTPServerDisconnected('contract test transport failure')
    async def skip_delay(_): pass
    monkeypatch.setattr(adapter,'_send_sync',failing)
    monkeypatch.setattr('backend.notifications.asyncio.sleep',skip_delay)
    result=asyncio.run(adapter.send(recipient='recipient@example.invalid',subject='test',body='offline contract test',idempotency_key='stable-delivery'))
    assert result.state=='failed' and result.attempts==3 and result.error_code=='smtp_delivery_failed'
    assert attempts==['<stable-delivery@pharmascope>']*3
