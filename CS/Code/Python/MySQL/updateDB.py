import pymysql as mq

db = mq.connect('localhost', 'yh', '123456', 'scm', charset='utf8')
cursor = db.cursor()
# SQL 更新语句
sql = "UPDATE SCMUSER SET STATUS=%s ,NAME =%s WHERE ACCOUNT=%s"
try:
    # 执行sql语句
    cursor.execute(sql, (2, 'vito', 'yh'))
    # 提交到数据库执行
    db.commit()
    print("更新行数为：%s " % cursor.rowcount)
except:
    # 发生错误时回滚
    db.rollback()
    print('insert is not execute!!!')
# 关闭游标，并关闭数据库
finally:
    cursor.close()
    db.close()
