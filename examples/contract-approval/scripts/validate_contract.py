contract = process.get_document("Карточка договора")
for field in ['Номер', 'Контрагент', 'Предмет договора']:
    if not contract.get(field):
        raise ValueError('Заполните обязательное поле договора: ' + field)
contract.validate()
sheet = process.get_document('Лист согласования')
sheet.set('Номер договора', contract.get('Номер'))
sheet.save()
log('Договор зарегистрирован: ' + str(contract.get('Номер')))
