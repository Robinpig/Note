import pymysql as mq

db = mq.connect('localhost', 'yh', '123456', 'scm', charset='utf8')
cursor = db.cursor()
# SQL 查询语句
sql = "SELECT * FROM SCMUSER"
# WHERE INCOME > %s" % (1000)
# 执行SQL语句
cursor.execute(sql)
# 获取所有记录列表
results = cursor.fetchall()
for row in results:
    account = row[0]
    password = row[1]
    name = row[2]
    createDate = row[3]
    status = row[4]
    # 打印结果
    print("account= %s,password= %s,name= %s,createDate= %s,status= %s :" +account,password, name, createDate, status)

# 关闭游标，并关闭数据库
cursor.close()
db.close()
