


Don't use it in DBMS

Transactional Safety

OS can flush dirty pages at any time and we can't stop it.

- OS COW(MongoDB)
- User COW(SQLite, MonetDB)
- Shadow Paging(LMDB)

I/O Stalls

Memory Cache pages are transparent and every read causes an I/O stall.

- OS hints


Error Handling

Validating pages is cumbersome and any access can cause a SIGBUS.

Performance Issues