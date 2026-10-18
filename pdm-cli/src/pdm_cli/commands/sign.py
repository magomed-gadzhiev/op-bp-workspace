"""№4c: генерация ключа, регистрация сертификата, криптоподпись маршрута.

Приватный ключ остаётся у пользователя — сервер получает только публичный
сертификат и проверяемую подпись канонического конверта.
"""
import base64
import datetime as _dt
import json
import os
from pathlib import Path

import click
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from rich.console import Console

from ..api_client import PdmApiClient
from ..config import load_config

console = Console()


def generate_self_signed(cn: str, days: int = 365):
    """Возвращает (private_pem: bytes, cert_pem: bytes) для Ed25519."""
    priv = Ed25519PrivateKey.generate()
    nb = _dt.datetime.now(_dt.timezone.utc)
    na = nb + _dt.timedelta(days=days)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(priv.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(nb).not_valid_after(na)
            .sign(priv, algorithm=None))
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    return priv_pem, cert.public_bytes(serialization.Encoding.PEM)


def sign_envelope(private_key_pem: bytes, envelope_json: str) -> str:
    """Подписывает байты конверта приватным ключом, возвращает base64-подпись."""
    priv = serialization.load_pem_private_key(private_key_pem, password=None)
    return base64.b64encode(priv.sign(envelope_json.encode('utf-8'))).decode()


def _write_private_key(path: str, data: bytes) -> None:
    """Пишет приватный ключ с правами 0o600 (на POSIX). Приватный ключ —
    единственный секрет схемы №4c, он не должен быть читаем другими."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _client(ctx, env):
    cwd = Path((ctx.obj or {}).get('cwd') or '.')
    cfg = load_config(cwd)
    return PdmApiClient(
        base_url=cfg.endpoint(env), api_key=cfg.api_key(env),
        cli_bypass_secret=cfg.cli_bypass_secret)


@click.command('gen-key')
@click.option('--cn', required=True, help='Subject CN (ФИО/логин).')
@click.option('--days', type=int, default=365, show_default=True)
@click.option('--out', default='priv.pem', show_default=True, help='Файл приватного ключа.')
@click.option('--cert', default='cert.pem', show_default=True, help='Файл сертификата.')
def gen_key(cn, days, out, cert):
    """Сгенерировать Ed25519-ключ и самоподписанный сертификат локально."""
    priv_pem, cert_pem = generate_self_signed(cn, days)
    _write_private_key(out, priv_pem)  # 0o600 — приватный ключ не для чужих глаз
    Path(cert).write_bytes(cert_pem)
    console.print(f'[green]Ключ: {out} (0600)  Сертификат: {cert}[/green]')


@click.command('register-key')
@click.option('--cert', required=True, help='Файл сертификата (PEM).')
@click.option('--env', type=click.Choice(['prod', 'sandbox']), default='prod', show_default=True)
@click.pass_context
def register_key(ctx, cert, env):
    """Зарегистрировать сертификат в PDM."""
    pem = Path(cert).read_text(encoding='utf-8')
    with _client(ctx, env) as client:
        r = client._client.post('/api/signing-keys/', json={'certificate_pem': pem})
        if r.status_code >= 400:
            raise click.ClickException(f'{r.status_code}: {r.text}')
        console.print(r.json())


@click.command('sign')
@click.option('--route', required=True, help='ID маршрута согласования.')
@click.option('--role', required=True, help='Роль (developer/checker/normcontrol/approver/tech_control).')
@click.option('--key', required=True, help='Файл приватного ключа (PEM).')
@click.option('--env', type=click.Choice(['prod', 'sandbox']), default='prod', show_default=True)
@click.pass_context
def sign(ctx, route, role, key, env):
    """Криптоподписать маршрут согласования: конверт от сервера → подпись → отправка."""
    private_key_pem = Path(key).read_bytes()
    with _client(ctx, env) as client:
        env_resp = client._client.get(
            f'/api/approval-routes/{route}/signing-envelope/', params={'role': role})
        if env_resp.status_code >= 400:
            raise click.ClickException(f'{env_resp.status_code}: {env_resp.text}')
        envelope_json = env_resp.json()['envelope_json']
        # Не подписываем вслепую: сверяем, что сервер вернул конверт ровно для
        # запрошенных маршрута и роли, прежде чем приложить приватный ключ.
        env = json.loads(envelope_json)
        if str(env.get('route_id')) != str(route) or env.get('role') != role:
            raise click.ClickException(
                f"Конверт сервера не совпадает с запросом "
                f"(route={env.get('route_id')}, role={env.get('role')}). Подпись отменена.")
        sig_b64 = sign_envelope(private_key_pem, envelope_json)
        r = client._client.post(
            f'/api/approval-routes/{route}/crypto-sign/',
            json={'role': role, 'envelope_json': envelope_json, 'signature_b64': sig_b64})
        if r.status_code >= 400:
            raise click.ClickException(f'{r.status_code}: {r.text}')
        console.print(r.json())
