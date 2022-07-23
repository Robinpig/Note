## Introduction

All the Redis commands are defined in the following way:

```
void foobarCommand(client *c) {
    printf("%s",c->argv[1]->ptr); /* Do something with the argument. */
    addReply(c,shared.ok); /* Reply something to the client. */
}

```

After the command operates in some way, it returns a reply to the client, usually using `addReply()` or a similar function defined inside `networking.c`.




## Links
