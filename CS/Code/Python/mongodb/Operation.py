import pymongo

mongodb_server_url = "mongodb://47.97.123.133:27017"
mongo = pymongo.MongoClient(mongodb_server_url)
db = mongo["test"]

collection = db.get_collection("mongo")

new_doc = {
    "Name": "Sun",
    "Gender": "Male",
    "Tel": "123456789",
    "SyncTime": 897678676,
    "Location": "Beijing"
}

print(collection.find_one({"Name": "vito"}))
update = {"Name": "Alice"}

# print(collection.delete_many({"Name": "Sun"}))
collection.insert_one(new_doc)
collection.update_one({"Name": "Sun"},
                      {"$set": {"Name": "vito", "tel": "3432412424"}})

collection.replace_one({"Name": "Sun"}, {"sense": "happy"})
print(collection.count_documents({"Name": "vito"}))
mongo.close()
