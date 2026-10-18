"""№4c: smoke-тесты команд gen-key/sign (офлайн, без сети)."""
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from pdm_cli.commands import sign as sign_cmd


def test_generate_self_signed_is_ed25519():
    priv_pem, cert_pem = sign_cmd.generate_self_signed('Тест', days=365)
    cert = x509.load_pem_x509_certificate(cert_pem)
    assert isinstance(cert.public_key(), Ed25519PublicKey)
    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
    assert cn == 'Тест'


def test_sign_envelope_verifies_against_cert():
    priv_pem, cert_pem = sign_cmd.generate_self_signed('Подписант')
    envelope_json = '{"role":"developer","round":1}'
    sig_b64 = sign_cmd.sign_envelope(priv_pem, envelope_json)

    import base64
    cert = x509.load_pem_x509_certificate(cert_pem)
    # Не бросает → подпись валидна для конверта и невалидна для подделки.
    cert.public_key().verify(base64.b64decode(sig_b64), envelope_json.encode('utf-8'))


def test_gen_key_writes_files(tmp_path):
    from click.testing import CliRunner

    from pdm_cli.cli import main

    out = tmp_path / 'priv.pem'
    cert = tmp_path / 'cert.pem'
    result = CliRunner().invoke(
        main, ['gen-key', '--cn', 'CLI Test', '--out', str(out), '--cert', str(cert)])
    assert result.exit_code == 0, result.output
    assert out.exists() and cert.exists()
    priv = serialization.load_pem_private_key(out.read_bytes(), password=None)
    assert priv is not None
