## Introduction

[**PowerJob**](https://github.com/KFCFans/PowerJob)**（原OhMyScheduler）****是全新一代分布式任务调度与计算框架**






@Slf4j
@EnableScheduling
@SpringBootApplication
public class PowerJobServerApplication {
    public static void main(String[] args) {

        pre();

        // Start SpringBoot application.
        try {
            SpringApplication.run(PowerJobServerApplication.class, args);
        } catch (Throwable t) {
            throw t;
        }
    }

    private static void pre() {
        log.info(TIPS);
        PropertyUtils.init();
    }

}



## Links


## References


1. [分布式 Java 任务调度平台 PowerJob](https://github.com/HelloGitHub-Team/Article/blob/master/contents/Java/PowerJob/catalog.md)