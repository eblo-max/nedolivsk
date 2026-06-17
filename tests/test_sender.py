"""Анти-флуд: лидирующий троттл косметических правок одного сообщения."""

from bot import sender


def test_claim_edit_throttles_same_message():
    sender._last_edit.clear()
    # первая правка проходит, мгновенная вторая того же сообщения — нет
    assert sender.claim_edit(10, 100, min_interval=100) is True
    assert sender.claim_edit(10, 100, min_interval=100) is False
    # другое сообщение в том же чате — свой счётчик, проходит
    assert sender.claim_edit(10, 101, min_interval=100) is True


def test_claim_edit_allows_after_interval():
    sender._last_edit.clear()
    # min_interval=0 — интервал всегда пройден, троттл не мешает
    assert sender.claim_edit(7, 7, min_interval=0) is True
    assert sender.claim_edit(7, 7, min_interval=0) is True


def test_claim_edit_self_prunes():
    sender._last_edit.clear()
    sender._last_edit.update({(0, i): 1.0 for i in range(4001)})
    sender.claim_edit(1, 1)                  # переполнение → оптовая чистка
    assert len(sender._last_edit) <= 2       # осталась только свежая запись
