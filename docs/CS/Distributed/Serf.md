## Introduction

[Serf]([Serf by HashiCorp](https://www.serf.io/)) relies on an efficient and lightweight gossip protocol to communicate with nodes. The Serf agents periodically exchange messages with each other in much the same way that a zombie apocalypse would occur: it starts with one zombie but soon infects everyone. In practice, the gossip is [very fast and extremely efficient.](https://www.serf.io/docs/internals/simulator.html)





