## Introduction

### Software Architecture

- Monolithic
- Service Oriented
- Microservices
- Service Mesh
- Serverless

#### Monolithic architecture

Monolithic architecture is the traditional structure for software applications. Analysts often compare it to microservices, a newer model for application development.
Although monolithic architecture has a long history, it is sometimes still superior to the microservices model.

Monolithic is an all-in-one architecture, wherein all aspects of the software operate as a single unit.
In the microservices model, components are modular, functioning independently, and coupled together as needed for optimal functionality.
When choosing between monolithic architecture and microservices, businesses evaluate factors such as agile integration, rapid testing, debugging, and scalability.

Monolithic architecture is a unified development model for software applications.
It has three components:

- Client-side user interface
- Server-side application
- Data interface

All three parts interact with a single database. Software built on this model operates with one base of code.
As a result, whenever stakeholders want to make updates or changes, they access the same set of code.
This can have ripple effects that impact user-side performance.

Monolithic architecture is the tried-and-true method of building applications.
It has an integrated development environment (IDE), which closely links all parts of the code.
Because it relies on that one set of code and does not create ad hoc linkages or loose coupling between tasks as microservices do, it is impossible to segment one particular task and integrate improvements without affecting the entire application.

**Pros of Monolithic Architecture**

- Simpler development and deployment
  There are lots of tools you can integrate to facilitate development. In addition, all actions are performed with one directory, which provides for easier deployment.
  With a monolithic core, developers don’t need to deploy changes or updates separately, as they can do it at once and save lots of time.
- Fewer cross-cutting concerns
  Most applications are reliant on a great deal of cross-cutting concerns, such as audit trails, logging, rate limiting, etc.
  Monolithic apps incorporate these concerns much easier due to their single code base. It’s easier to hook up components to these concerns when everything runs in the same app.
- Better performance
  If built properly, monolithic apps are usually more performant than microservice-based apps.
  An app with a microservices architecture might need to make 40 API calls to 40 different microservices to load each screen, for example, which obviously results in slower performance.
  Monolithic apps, in turn, allow faster communication between software components due to shared code and memory.

**Cons of Monolithic Architecture**

Despite its benefits, there are some potential downsides to monolithic architecture.
These downsides arise because of the monolith's defining feature — the all-in-one structure.
They include:

- Difficult to adopt new technologies
  If there’s a need to add some new technology to your app, developers may face barriers to adoption. Adding new technology means rewriting the whole application, which is costly and time-consuming.
- Limited agility
  In monolithic apps, every small update requires a full redeployment. Thus, all developers have to wait until it’s done. When several teams are working on the same project, agility can be reduced greatly.

The monolithic model isn’t outdated, and it still works great in some cases.
Some giant companies like Etsy stay monolithic despite today’s popularity of microservices.
Monolithic software architecture can be beneficial if your team is at the founding stage, you’re building an unproven product, and you have no experience with microservices.
Monolithic is perfect for startups that need to get a product up and running as soon as possible.
However, certain issues mentioned above come with the monolithic package.

#### SOA

A service-oriented architecture (SOA) is a software architecture style that refers to an application composed of discrete and loosely coupled software agents that perform a required function. SOA has two main roles: a service provider and a service consumer.
Both of these roles can be played by a software agent. The concept of SOA lies in the following: an application can be designed and built in a way that its modules are integrated seamlessly and can be easily reused.

**Pros of SOA**

- Reusability of services
  Due to the self-contained and loosely coupled nature of functional components in service-oriented applications, these components can be reused in multiple applications without influencing other services.
- Better maintainability
  Since each software service is an independent unit, it’s easy to update and maintain it without hurting other services. For example, large enterprise apps can be managed easier when broken into services.
- Higher reliability
  Services are easier to debug and test than are huge chunks of code like in the monolithic approach. This, in turn, makes SOA-based products more reliable.
- Parallel development
  As a service-oriented architecture consists of layers, it advocates parallelism in the development process. Independent services can be developed in parallel and completed at the same time.
  Below, you can see how SOA app development is executed by several developers in parallel:

**Cons of SOA**

- Complex management
  The main drawback of a service-oriented architecture is its complexity. Each service has to ensure that messages are delivered in time.
  The number of these messages can be over a million at a time, making it a big challenge to manage all services.
- High investment costs
  SOA development requires a great upfront investment of human resources, technology, and development.
- Extra overload
  In SOA, all inputs are validated before one service interacts with another service. When using multiple services, this increases response time and decreases overall performance.

The SOA approach is best suited for complex enterprise systems such as those for banks.
A banking system is extremely hard to break into microservices. But a monolithic approach also isn’t good for a banking system as one part could hurt the whole app.
The best solution is to use the SOA approach and organize complex apps into isolated independent services.

#### Microservice architecture

Microservice is a type of service-oriented software architecture that focuses on building a series of autonomous components that make up an app.
Unlike monolithic apps built as a single indivisible unit, microservice apps consist of multiple independent components that are glued together with APIs.

**Pros of microservices**

- Easy to develop, test, and deploy
  The biggest advantage of microservices over other architectures is that small single services can be built, tested, and deployed independently.
  Since a deployment unit is small, it facilitates and speeds up development and release. Besides, the release of one unit isn’t limited by the release of another unit that isn’t finished.
  And the last plus here is that the risks of deployment are reduced as developers deploy parts of the software, not the whole app.
- Increased agility
  With microservices, several teams can work on their services independently and quickly. Each individual part of an application can be built independently due to the decoupling of microservice components.
  For example, you may have a team of 100 people working on the whole app (like in the monolithic approach), or you can have 10 teams of 10 people developing different services for the app. Let’s imagine this visually.
  Increased agility allows developers to update system components without bringing down the application.
  Moreover, agility provides a safer deployment process and improved uptime. New features can be added as needed without waiting for the entire app to launch.
- Ability to scale horizontally
  Vertical scaling (running the same software but on bigger machines) can be limited by the capacity of each service.
  But horizontal scaling (creating more services in the same pool) isn’t limited and can run dynamically with microservices. Furthermore, horizontal scaling can be completely automated.

**Cons of microservices**

- Complexity
  The biggest disadvantage of microservices lies in their complexity. Splitting an application into independent microservices entails more artifacts to manage.
  This type of architecture requires careful planning, enormous effort, team resources, and skills. The reasons for high complexity are the following:
  - Increased demand for automation, as every service should be tested and monitored
  - Available tools don’t work with service dependencies
  - Data consistency and transaction management becomes harder as each service has a database
- Security concerns
  In a microservices application, each functionality that communicates externally via an API increases the chance of attacks.
  These attacks can happen only if proper security measurements aren’t implemented when building an app.
- Different programming languages
  The ability to choose different programming languages is two sides of the same coin. Using different languages make deployment more difficult.
  In addition, it’s harder to switch programmers between development phases when each service is written in a different language.

**Microservices are good, but not for all types of apps.** This pattern works great for evolving applications and complex systems.
When an application is large and needs to be flexible and scalable, microservices are beneficial.

Monolithic apps consist of interdependent, indivisible units and feature very low development speed.
SOA is broken into smaller, moderately coupled services, and features slow development.
Microservices are very small, loosely coupled independent services and feature rapid continuous development.

#### Serverless architecture

Serverless architecture is a cloud computing approach to building and running apps and services without the need for infrastructure management.
In serverless apps, code execution is managed by a server, allowing developers to deploy code without worrying about server maintenance and provision.
In fact, serverless doesn’t mean “no server.” The application is still running on servers, but a third-party cloud service like AWS takes full responsibility for these servers.
A serverless architecture eliminates the need for extra resources, application scaling, server maintenance, and database and storage systems.

The serverless architecture incorporates two concepts:

- **FaaS ( Function as a Service)** – a cloud computing model which allows developers to upload pieces of functionality to the cloud and let these pieces be executed independently
- **BaaS ( Backend as a Service)** – a cloud computing model which allows developers to outsource backend aspects (database management, cloud storage, hosting, user authentication, etc.) and write and maintain only the frontend part

When using a serverless architecture, developers can focus on the product itself without worrying about server management or execution environments.
This allows developers to focus on developing products with high reliability and scalability.

**Pros of a serverless architecture**

- Easy to deploy
  In serverless apps, developers don’t need to worry about infrastructure. This allows them to focus on the code itself.
  Serverless architecture allows you to spin up an app extremely fast, as deployment takes only hours or days (compared to days or weeks with a traditional approach).
- Lower costs
  Going serverless reduces costs. Since you don’t need to handle databases, some logic, and servers, you can not only create higher quality code but also cut expenses.
  When using a serverless model, you’re only charged for the CPU cycles and memory you actually use.
- Enhanced scalability
  Many business owners want their apps to become influential and scalable like Google or Facebook. Serverless computing makes scaling automatic and seamless.
  Your app will automatically scale as your load or user base increases without affecting performance.
  Serverless apps can handle a huge number of requests, whereas a traditional app will be overwhelmed by a sudden increase in requests.

**Cons of a serverless architecture**

- Vendor lock-in
  Vendor lock-in describes a situation when you give a vendor full control of your operations. As a result, changes to business logic are limited and migration from one vendor to another might be challenging.
- Not for long-term tasks
  A serverless model isn’t suitable for long-term operations. Serverless apps are good for short real-time processes, but if a task takes more than five minutes, a serverless app will need additional FaaS functionality.

Serverless software architecture is beneficial for accomplishing one-time tasks and auxiliary processes. It works great for client-heavy apps and apps that are growing fast and need to scale limitlessly.

## References

1. [凤凰架构 构建可靠的大型分布式系统](https://icyfenix.cn/)
2. [Best Architecture for an MVP: Monolith, SOA, Microservices, or Serverless?](https://rubygarage.org/blog/monolith-soa-microservices-serverless)
