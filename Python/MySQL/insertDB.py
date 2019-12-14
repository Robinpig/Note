import pymysql as mq

db = mq.connect('localhost', 'yh', '123456', 'scm', charset='utf8')
cursor = db.cursor()
account = 'x4xx'
password = 'sdvs'
name = 'dsbsb'
createDate = '2019-12-14'
status = 0
# SQL 插入语句
sql = "INSERT INTO SCMUSER(ACCOUNT, PASSWORD, NAME, CREATEDATE, STATUS) " \
      "VALUES (%s, %s, %s, %s, %s)"

# 执行sql语句
try:
    cursor.execute(sql, (account, password, name, createDate, status))
    # 提交到数据库执行
    db.commit()
    print("插入行数为：%s " % cursor.rowcount)
except:
    # 发生错误时回滚
    db.rollback()
    print('insert is not execute!!!')
# 关闭游标，并关闭数据库
finally:
    cursor.close()
    db.close()
