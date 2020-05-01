import pymongo

mongodb_server_url = "mongodb://47.97.123.133:27017"
mongo = pymongo.MongoClient(mongodb_server_url)
db = mongo["test"]

collection = db.get_collection("mongo")

print("Number of Documents:" + str(collection.find().count()))

mongo.close()
