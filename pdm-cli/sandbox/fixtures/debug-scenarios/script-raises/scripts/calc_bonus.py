"""
Иллюстративный скрипт с багом (для тренировки pdm:debug-failed-run).
Реально не исполняется — это шаблон для встраивания в БП sandbox-стенда.

Баг: при department='UNKNOWN' lookup_rate() возвращает None, и на
строке 12 происходит TypeError: unsupported operand type(s) for *.
"""


def lookup_rate(department: str):
    rates = {"R&D": 0.15, "SALES": 0.10}
    return rates.get(department)  # None для UNKNOWN


def calc(amount: float, department: str) -> float:
    rate = lookup_rate(department)
    return rate * amount  # ← line 12, упадёт когда rate is None


if __name__ == "__main__":
    import sys, json
    payload = json.loads(sys.stdin.read())
    print(json.dumps({"bonus": calc(payload["amount"], payload["department"])}))
