sheet = process.get_document('Лист согласования')
decision = sheet.get('Решение руководителя')
if not decision:
    raise ValueError('Укажите решение руководителя в листе согласования')
contract = process.get_document("Карточка договора")
contract.set('Статус согласования', decision)
contract.save()
log('Решение руководителя записано в договор: ' + str(decision))
