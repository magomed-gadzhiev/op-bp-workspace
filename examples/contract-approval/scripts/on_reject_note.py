contract = process.get_document("Карточка договора")
contract.set('Статус согласования', 'Возвращён на доработку')
contract.save(validate=False)
log('Договор возвращён на доработку')
