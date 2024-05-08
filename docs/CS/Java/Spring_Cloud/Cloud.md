## Introduction

Cloud Native is a style of application development that encourages easy adoption of best practices in the areas of continuous delivery and value-driven development. 
A related discipline is that of building 12-factor Applications, in which development practices are aligned with delivery and operations goals-for instance, by using declarative programming and management and monitoring.
Cloud native refers less to where an application resides and more to how it is built and deployed. 
A cloud native application consists of discrete, reusable components that are known as microservices that are designed to integrate into any cloud environment.

- A cloud native application consists of discrete, reusable components that are known as microservices that are designed to integrate into any cloud environment.
- These microservices act as building blocks and are often packaged in containers.
- Microservices work together as a whole to comprise an application, yet each can be independently scaled, continuously improved, and quickly iterated through automation and orchestration processes.
- The flexibility of each microservice adds to the agility and continuous improvement of cloud-native applications.

> “Cloud-native technology is when engineers and software people utilize cloud computing to build tech that’s faster and more resilient, and they do that to meet customer demand really quickly.” —Priyanka Sharma, Cloud Native Computing Foundation

## Principles for cloud-native architecture

The principle of architecting for the cloud, a.k.a. cloud-native architecture, focuses on how to optimize system architectures for the unique capabilities of the cloud.
Traditional architecture tends to optimize for a fixed, high-cost infrastructure, which requires considerable manual effort to modify.
Traditional architecture therefore focuses on the resilience and performance of a relatively small fixed number of components.
In the cloud however, such a fixed infrastructure makes much less sense because cloud is charged based on usage (so you save money when you can reduce your footprint) and it’s also much easier to automate (so automatically scaling-up and down is much easier).
Therefore, cloud-native architecture focuses on achieving resilience and scale though horizontal scaling, distributed processing, and automating the replacement of failed components.

> The only constant is change

### Principle 1: Design for automation

Automation has always been a best practice for software systems, but cloud makes it easier than ever to automate the infrastructure as well as components that sit above it.
Although the upfront investment is often higher, favouring an automated solution will almost always pay off in the medium term in terms of effort, but also in terms of the resilience and performance of your system.
Automated processes can repair, scale, deploy your system far faster than people can.
As we discuss later on, architecture in the cloud is not a one-shot deal, and automation is no exception—as you find new ways that your system needs to take action, so you will find new things to automate.

### Principle 2: Be smart with state

Storing of 'state', be that user data (e.g., the items in the users shopping cart, or their employee number) or system state (e.g., how many instances of a job are running, what version of code is running in production), is the hardest aspect of architecting a distributed, cloud-native architecture.
You should therefore architect your system to be intentional about when, and how, you store state, and design components to be stateless wherever you can.

### Principle 3: Favor managed services

Cloud is more than just infrastructure. Most cloud providers offer a rich set of managed services, providing all sorts of functionality that relieve you of the headache of managing the backend software or infrastructure.
However, many organizations are cautious about taking advantage of these services because they are concerned about being 'locked in' to a given provider.
This is a valid concern, but managed services can often save the organization hugely in time and operational overhead.

### Principle 4: Practice defense in depth

Traditional architectures place a lot of faith in perimeter security, crudely a hardened network perimeter with 'trusted things' inside and 'untrusted things' outside.
Unfortunately, this approach has always been vulnerable to insider attacks, as well as external threats such as spear phishing.
Moreover, the increasing pressure to provide flexible and mobile working has further undermined the network perimeter.
Cloud-native architectures have their origins in internet-facing services, and so have always needed to deal with external attacks.
Therefore they adopt an approach of defense-in-depth by applying authentication between each component, and by minimizing the trust between those components (even if they are 'internal'). As a result, there is no 'inside' and 'outside'.

### Principle 5: Always be architecting

One of the core characteristics of a cloud-native system is that it’s always evolving, and that's equally true of the architecture.
As a cloud-native architect, you should always seek to refine, simplify and improve the architecture of the system, as the needs of the organization change, the landscape of your IT systems change, and the capabilities of your cloud provider itself change.
While this undoubtedly requires constant investment, the lessons of the past are clear: to evolve, grow, and respond, IT systems need to live and breathe and change.
Dead, ossifying IT systems rapidly bring the organization to a standstill, unable to respond to new threats and opportunities.

## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)
- [Container](/docs/CS/Container/Container.md)

## References

1. [What Is Cloud Native and Why Is It Important?](https://builtin.com/articles/what-is-cloud-native)
2. [What is cloud native?](https://www.ibm.com/topics/cloud-native)
3. [5 principles for cloud-native architecture—what it is and how to master it](https://cloud.google.com/blog/products/application-development/5-principles-for-cloud-native-architecture-what-it-is-and-how-to-master-it)
