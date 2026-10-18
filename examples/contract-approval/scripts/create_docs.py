if not documents.find("Карточка договора"):
    process.create_document("Карточка договора")
if not documents.find('Лист согласования'):
    process.create_document('Лист согласования')
log('Документы заявки созданы')
