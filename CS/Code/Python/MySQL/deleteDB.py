import pymysql as mq

db = mq.connect('localhost', 'yh', '123456', 'scm', charset='utf8')
cursor = db.cursor()
# SQL 删除语句
sql = "DELETE FROM SCMUSER WHERE status = " + "0"
try:
    # 执行sql语句
    cursor.execute(sql)
    # 提交到数据库执行
    db.commit()
    print("删除行数为：%s "%cursor.rowcount)
except:
    # 发生错误时回滚
    db.rollback()
    print('delete is not execute!!!')
    # 关闭游标，并关闭数据库
finally:
    cursor.close()
    db.close()
