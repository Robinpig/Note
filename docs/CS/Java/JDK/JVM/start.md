
1. RegisterThread
2. InitializeJVM   CreateJavaVM
2. check args
3. LoadMainClass 
4. PostJVMInit
5. invoke main method

```cpp
// java.c
int
JavaMain(void* _args)
{
    JavaMainArgs *args = (JavaMainArgs *)_args;
    int argc = args->argc;
    char **argv = args->argv;
    int mode = args->mode;
    char *what = args->what;
    InvocationFunctions ifn = args->ifn;

    JavaVM *vm = 0;
    JNIEnv *env = 0;
    jclass mainClass = NULL;
    jclass appClass = NULL; // actual application class being launched
    jmethodID mainID;
    jobjectArray mainArgs;
    int ret = 0;
    jlong start = 0, end = 0;

    RegisterThread();

    /* Initialize the virtual machine */
    start = CurrentTimeMicros();
    if (!InitializeJVM(&vm, &env, &ifn)) {
        JLI_ReportErrorMessage(JVM_ERROR1);
        exit(1);
    }

    if (showSettings != NULL) {
        ShowSettings(env, showSettings);
        CHECK_EXCEPTION_LEAVE(1);
    }

    // show resolved modules and continue
    if (showResolvedModules) {
        ShowResolvedModules(env);
        CHECK_EXCEPTION_LEAVE(1);
    }

    // list observable modules, then exit
    if (listModules) {
        ListModules(env);
        CHECK_EXCEPTION_LEAVE(1);
        LEAVE();
    }

    // describe a module, then exit
    if (describeModule != NULL) {
        DescribeModule(env, describeModule);
        CHECK_EXCEPTION_LEAVE(1);
        LEAVE();
    }

    if (printVersion || showVersion) {
        PrintJavaVersion(env, showVersion);
        CHECK_EXCEPTION_LEAVE(0);
        if (printVersion) {
            LEAVE();
        }
    }

    // modules have been validated at startup so exit
    if (validateModules) {
        LEAVE();
    }

    /* If the user specified neither a class name nor a JAR file */
    if (printXUsage || printUsage || what == 0 || mode == LM_UNKNOWN) {
        PrintUsage(env, printXUsage);
        CHECK_EXCEPTION_LEAVE(1);
        LEAVE();
    }

    FreeKnownVMs(); /* after last possible PrintUsage */

    if (JLI_IsTraceLauncher()) {
        end = CurrentTimeMicros();
        JLI_TraceLauncher("%ld micro seconds to InitializeJVM\n", (long)(end-start));
    }

    /* At this stage, argc/argv have the application's arguments */
    if (JLI_IsTraceLauncher()){
        int i;
        printf("%s is '%s'\n", launchModeNames[mode], what);
        printf("App's argc is %d\n", argc);
        for (i=0; i < argc; i++) {
            printf("    argv[%2d] = '%s'\n", i, argv[i]);
        }
    }

    ret = 1;

    /*
     * Get the application's main class. It also checks if the main
     * method exists.
     *
     * See bugid 5030265.  The Main-Class name has already been parsed
     * from the manifest, but not parsed properly for UTF-8 support.
     * Hence the code here ignores the value previously extracted and
     * uses the pre-existing code to reextract the value.  This is
     * possibly an end of release cycle expedient.  However, it has
     * also been discovered that passing some character sets through
     * the environment has "strange" behavior on some variants of
     * Windows.  Hence, maybe the manifest parsing code local to the
     * launcher should never be enhanced.
     *
     * Hence, future work should either:
     *     1)   Correct the local parsing code and verify that the
     *          Main-Class attribute gets properly passed through
     *          all environments,
     *     2)   Remove the vestages of maintaining main_class through
     *          the environment (and remove these comments).
     *
     * This method also correctly handles launching existing JavaFX
     * applications that may or may not have a Main-Class manifest entry.
     */
    mainClass = LoadMainClass(env, mode, what);
    CHECK_EXCEPTION_NULL_LEAVE(mainClass);
    /*
     * In some cases when launching an application that needs a helper, e.g., a
     * JavaFX application with no main method, the mainClass will not be the
     * applications own main class but rather a helper class. To keep things
     * consistent in the UI we need to track and report the application main class.
     */
    appClass = GetApplicationClass(env);
    NULL_CHECK_RETURN_VALUE(appClass, -1);

    /* Build platform specific argument array */
    mainArgs = CreateApplicationArgs(env, argv, argc);
    CHECK_EXCEPTION_NULL_LEAVE(mainArgs);

    if (dryRun) {
        ret = 0;
        LEAVE();
    }

    /*
     * PostJVMInit uses the class name as the application name for GUI purposes,
     * for example, on OSX this sets the application name in the menu bar for
     * both SWT and JavaFX. So we'll pass the actual application class here
     * instead of mainClass as that may be a launcher or helper class instead
     * of the application class.
     */
    PostJVMInit(env, appClass, vm);
    CHECK_EXCEPTION_LEAVE(1);

    /*
     * The LoadMainClass not only loads the main class, it will also ensure
     * that the main method's signature is correct, therefore further checking
     * is not required. The main method is invoked here so that extraneous java
     * stacks are not in the application stack trace.
     */
    mainID = (*env)->GetStaticMethodID(env, mainClass, "main",
                                       "([Ljava/lang/String;)V");
    CHECK_EXCEPTION_NULL_LEAVE(mainID);

    /* Invoke main method. */
    (*env)->CallStaticVoidMethod(env, mainClass, mainID, mainArgs);

    /*
     * The launcher's exit code (in the absence of calls to
     * System.exit) will be non-zero if main threw an exception.
     */
    ret = (*env)->ExceptionOccurred(env) == NULL ? 0 : 1;

    LEAVE();
}

```