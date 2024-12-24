## Introduction

生成sql

在[finisher_api.go](https://github.com/go-gorm/gorm/blob/master/finisher_api.go)文件，声明了`First`方法

```go
// First finds the first record ordered by primary key, matching given conditions conds
func (db *DB) First(dest interface{}, conds ...interface{}) (tx *DB) {
    tx = db.Limit(1).Order(clause.OrderByColumn{
        Column: clause.Column{Table: clause.CurrentTable, Name: clause.PrimaryKey},
    })
    if len(conds) > 0 {
        if exprs := tx.Statement.BuildCondition(conds[0], conds[1:]...); len(exprs) > 0 {
            tx.Statement.AddClause(clause.Where{Exprs: exprs})
        }
    }
    tx.Statement.RaiseErrorOnNotFound = true
    tx.Statement.Dest = dest
    return tx.callbacks.Query().Execute(tx)
}
```


```go

// Config GORM config
type Config struct {
    // 。。。
	callbacks  *callbacks
	cacheStore *sync.Map
}

type callback struct {
	name      string
	before    string
	after     string
	remove    bool
	replace   bool
	match     func(*DB) bool
	handler   func(*DB)
	processor *processor
}

func (cs *callbacks) Query() *processor {
    return cs.processors["query"]
}
```



在mysql中的实现




```go
func RegisterDefaultCallbacks(db *gorm.DB, config *Config) {
    enableTransaction := func(db *gorm.DB) bool {
        return !db.SkipDefaultTransaction
    }

    // 省略CREATE DELTE UPDATE
    if len(config.QueryClauses) == 0 {
        config.QueryClauses = queryClauses
    }

    queryCallback := db.Callback().Query()
    queryCallback.Register("gorm:query", Query)
    queryCallback.Register("gorm:preload", Preload)
    queryCallback.Register("gorm:after_query", AfterQuery)
    queryCallback.Clauses = config.QueryClauses

    rowCallback := db.Callback().Row()
    rowCallback.Register("gorm:row", RowQuery)
    rowCallback.Clauses = config.QueryClauses

    rawCallback := db.Callback().Raw()
    rawCallback.Register("gorm:raw", RawExec)
    rawCallback.Clauses = config.QueryClauses
}
```



注册Query函数

```go
func Query(db *gorm.DB) {
    if db.Error == nil {
        BuildQuerySQL(db)

        if !db.DryRun && db.Error == nil {
            rows, err := db.Statement.ConnPool.QueryContext(db.Statement.Context, db.Statement.SQL.String(), db.Statement.Vars...)
            if err != nil {
                db.AddError(err)
                return
            }
            defer func() {
                db.AddError(rows.Close())
            }()
            gorm.Scan(rows, db, 0)
        }
    }
}
```


```go
func BuildQuerySQL(db *gorm.DB) {
    if db.Statement.Schema != nil {
        for _, c := range db.Statement.Schema.QueryClauses {
            db.Statement.AddClause(c)
        }
    }

    if db.Statement.SQL.Len() == 0 {
        db.Statement.SQL.Grow(100)
        clauseSelect := clause.Select{Distinct: db.Statement.Distinct}

        if db.Statement.ReflectValue.Kind() == reflect.Struct && db.Statement.ReflectValue.Type() == db.Statement.Schema.ModelType {
            var conds []clause.Expression
            for _, primaryField := range db.Statement.Schema.PrimaryFields {
                if v, isZero := primaryField.ValueOf(db.Statement.Context, db.Statement.ReflectValue); !isZero {
                    conds = append(conds, clause.Eq{Column: clause.Column{Table: db.Statement.Table, Name: primaryField.DBName}, Value: v})
                }
            }

            if len(conds) > 0 {
                db.Statement.AddClause(clause.Where{Exprs: conds})
            }
        }

        if len(db.Statement.Selects) > 0 {
            clauseSelect.Columns = make([]clause.Column, len(db.Statement.Selects))
            for idx, name := range db.Statement.Selects {
                if db.Statement.Schema == nil {
                    clauseSelect.Columns[idx] = clause.Column{Name: name, Raw: true}
                } else if f := db.Statement.Schema.LookUpField(name); f != nil {
                    clauseSelect.Columns[idx] = clause.Column{Name: f.DBName}
                } else {
                    clauseSelect.Columns[idx] = clause.Column{Name: name, Raw: true}
                }
            }
        } else if db.Statement.Schema != nil && len(db.Statement.Omits) > 0 {
            selectColumns, _ := db.Statement.SelectAndOmitColumns(false, false)
            clauseSelect.Columns = make([]clause.Column, 0, len(db.Statement.Schema.DBNames))
            for _, dbName := range db.Statement.Schema.DBNames {
                if v, ok := selectColumns[dbName]; (ok && v) || !ok {
                    clauseSelect.Columns = append(clauseSelect.Columns, clause.Column{Table: db.Statement.Table, Name: dbName})
                }
            }
        } else if db.Statement.Schema != nil && db.Statement.ReflectValue.IsValid() {
            queryFields := db.QueryFields
            if !queryFields {
                switch db.Statement.ReflectValue.Kind() {
                case reflect.Struct:
                    queryFields = db.Statement.ReflectValue.Type() != db.Statement.Schema.ModelType
                case reflect.Slice:
                    queryFields = db.Statement.ReflectValue.Type().Elem() != db.Statement.Schema.ModelType
                }
            }

            if queryFields {
                stmt := gorm.Statement{DB: db}
                // smaller struct
                if err := stmt.Parse(db.Statement.Dest); err == nil && (db.QueryFields || stmt.Schema.ModelType != db.Statement.Schema.ModelType) {
                    clauseSelect.Columns = make([]clause.Column, len(stmt.Schema.DBNames))

                    for idx, dbName := range stmt.Schema.DBNames {
                        clauseSelect.Columns[idx] = clause.Column{Table: db.Statement.Table, Name: dbName}
                    }
                }
            }
        }

        // inline joins
        fromClause := clause.From{}
        if v, ok := db.Statement.Clauses["FROM"].Expression.(clause.From); ok {
            fromClause = v
        }

        if len(db.Statement.Joins) != 0 || len(fromClause.Joins) != 0 {
            if len(db.Statement.Selects) == 0 && len(db.Statement.Omits) == 0 && db.Statement.Schema != nil {
                clauseSelect.Columns = make([]clause.Column, len(db.Statement.Schema.DBNames))
                for idx, dbName := range db.Statement.Schema.DBNames {
                    clauseSelect.Columns[idx] = clause.Column{Table: db.Statement.Table, Name: dbName}
                }
            }

            specifiedRelationsName := make(map[string]interface{})
            for _, join := range db.Statement.Joins {
                if db.Statement.Schema != nil {
                    var isRelations bool // is relations or raw sql
                    var relations []*schema.Relationship
                    relation, ok := db.Statement.Schema.Relationships.Relations[join.Name]
                    if ok {
                        isRelations = true
                        relations = append(relations, relation)
                    } else {
                        // handle nested join like "Manager.Company"
                        nestedJoinNames := strings.Split(join.Name, ".")
                        if len(nestedJoinNames) > 1 {
                            isNestedJoin := true
                            gussNestedRelations := make([]*schema.Relationship, 0, len(nestedJoinNames))
                            currentRelations := db.Statement.Schema.Relationships.Relations
                            for _, relname := range nestedJoinNames {
                                // incomplete match, only treated as raw sql
                                if relation, ok = currentRelations[relname]; ok {
                                    gussNestedRelations = append(gussNestedRelations, relation)
                                    currentRelations = relation.FieldSchema.Relationships.Relations
                                } else {
                                    isNestedJoin = false
                                    break
                                }
                            }

                            if isNestedJoin {
                                isRelations = true
                                relations = gussNestedRelations
                            }
                        }
                    }

                    if isRelations {
                        genJoinClause := func(joinType clause.JoinType, parentTableName string, relation *schema.Relationship) clause.Join {
                            tableAliasName := relation.Name
                            if parentTableName != clause.CurrentTable {
                                tableAliasName = utils.NestedRelationName(parentTableName, tableAliasName)
                            }

                            columnStmt := gorm.Statement{
                                Table: tableAliasName, DB: db, Schema: relation.FieldSchema,
                                Selects: join.Selects, Omits: join.Omits,
                            }

                            selectColumns, restricted := columnStmt.SelectAndOmitColumns(false, false)
                            for _, s := range relation.FieldSchema.DBNames {
                                if v, ok := selectColumns[s]; (ok && v) || (!ok && !restricted) {
                                    clauseSelect.Columns = append(clauseSelect.Columns, clause.Column{
                                        Table: tableAliasName,
                                        Name:  s,
                                        Alias: utils.NestedRelationName(tableAliasName, s),
                                    })
                                }
                            }

                            exprs := make([]clause.Expression, len(relation.References))
                            for idx, ref := range relation.References {
                                if ref.OwnPrimaryKey {
                                    exprs[idx] = clause.Eq{
                                        Column: clause.Column{Table: parentTableName, Name: ref.PrimaryKey.DBName},
                                        Value:  clause.Column{Table: tableAliasName, Name: ref.ForeignKey.DBName},
                                    }
                                } else {
                                    if ref.PrimaryValue == "" {
                                        exprs[idx] = clause.Eq{
                                            Column: clause.Column{Table: parentTableName, Name: ref.ForeignKey.DBName},
                                            Value:  clause.Column{Table: tableAliasName, Name: ref.PrimaryKey.DBName},
                                        }
                                    } else {
                                        exprs[idx] = clause.Eq{
                                            Column: clause.Column{Table: tableAliasName, Name: ref.ForeignKey.DBName},
                                            Value:  ref.PrimaryValue,
                                        }
                                    }
                                }
                            }

                            {
                                onStmt := gorm.Statement{Table: tableAliasName, DB: db, Clauses: map[string]clause.Clause{}}
                                for _, c := range relation.FieldSchema.QueryClauses {
                                    onStmt.AddClause(c)
                                }

                                if join.On != nil {
                                    onStmt.AddClause(join.On)
                                }

                                if cs, ok := onStmt.Clauses["WHERE"]; ok {
                                    if where, ok := cs.Expression.(clause.Where); ok {
                                        where.Build(&onStmt)

                                        if onSQL := onStmt.SQL.String(); onSQL != "" {
                                            vars := onStmt.Vars
                                            for idx, v := range vars {
                                                bindvar := strings.Builder{}
                                                onStmt.Vars = vars[0 : idx+1]
                                                db.Dialector.BindVarTo(&bindvar, &onStmt, v)
                                                onSQL = strings.Replace(onSQL, bindvar.String(), "?", 1)
                                            }

                                            exprs = append(exprs, clause.Expr{SQL: onSQL, Vars: vars})
                                        }
                                    }
                                }
                            }

                            return clause.Join{
                                Type:  joinType,
                                Table: clause.Table{Name: relation.FieldSchema.Table, Alias: tableAliasName},
                                ON:    clause.Where{Exprs: exprs},
                            }
                        }

                        parentTableName := clause.CurrentTable
                        for _, rel := range relations {
                            // joins table alias like "Manager, Company, Manager__Company"
                            nestedAlias := utils.NestedRelationName(parentTableName, rel.Name)
                            if _, ok := specifiedRelationsName[nestedAlias]; !ok {
                                fromClause.Joins = append(fromClause.Joins, genJoinClause(join.JoinType, parentTableName, rel))
                                specifiedRelationsName[nestedAlias] = nil
                            }

                            if parentTableName != clause.CurrentTable {
                                parentTableName = utils.NestedRelationName(parentTableName, rel.Name)
                            } else {
                                parentTableName = rel.Name
                            }
                        }
                    } else {
                        fromClause.Joins = append(fromClause.Joins, clause.Join{
                            Expression: clause.NamedExpr{SQL: join.Name, Vars: join.Conds},
                        })
                    }
                } else {
                    fromClause.Joins = append(fromClause.Joins, clause.Join{
                        Expression: clause.NamedExpr{SQL: join.Name, Vars: join.Conds},
                    })
                }
            }

            db.Statement.AddClause(fromClause)
        } else {
            db.Statement.AddClauseIfNotExists(clause.From{})
        }

        db.Statement.AddClauseIfNotExists(clauseSelect)

        db.Statement.Build(db.Statement.BuildClauses...)
    }
}
```

通过clauses进行sql的组装
```go
// Build build sql with clauses names
func (stmt *Statement) Build(clauses ...string) {
    var firstClauseWritten bool

    for _, name := range clauses {
        if c, ok := stmt.Clauses[name]; ok {
            if firstClauseWritten {
                stmt.WriteByte(' ')
            }

            firstClauseWritten = true
            if b, ok := stmt.DB.ClauseBuilders[name]; ok {
                b(c, stmt)
            } else {
                c.Build(stmt)
            }
        }
    }
}
```






## Links

- [Golang](/docs/CS/Go/Go.md)