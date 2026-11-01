from fatball import secrets


def test_password_round_trip_stays_in_the_test_keyring(memory_keyring):
    assert secrets.get_password() is None
    secrets.set_password("pw")
    assert secrets.get_password() == "pw"
    assert memory_keyring.items == {(secrets.SERVICE, secrets.ACCOUNT): "pw"}
