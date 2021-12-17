## Introduction


[git clone javac source code](git@github.com:Robinpig/javac-source-code-reading.git) and copy to a new project.


## Lexical Analysis

```java

package com.sun.tools.javac.main;

/** This class provides a command line interface to the javac compiler.
 *
 *  <p><b>This is NOT part of any supported API.
 *  If you write code that depends on this, you do so at your own risk.
 *  This code and its internal interfaces are subject to change or
 *  deletion without notice.</b>
 */
public class Main {
    public Result compile(String[] args) {
        Context context = new Context();
        JavacFileManager.preRegister(context); // can't create it until Log has been set up
        Result result = compile(args, context);
        if (fileManager instanceof JavacFileManager) {
            // A fresh context was created above, so jfm must be a JavacFileManager
            ((JavacFileManager) fileManager).close();
        }
        return result;
    }


    public Result compile(String[] args,
                          String[] classNames,
                          Context context,
                          List<JavaFileObject> fileObjects,
                          Iterable<? extends Processor> processors)
    {
        context.put(Log.outKey, out);
        log = Log.instance(context);

        if (options == null)
            options = Options.instance(context); // creates a new one

        filenames = new LinkedHashSet<File>();
        classnames = new ListBuffer<String>();
        JavaCompiler comp = null;
        /*
         * TODO: Logic below about what is an acceptable command line
         * should be updated to take annotation processing semantics
         * into account.
         */
        try {
            if (args.length == 0
                    && (classNames == null || classNames.length == 0)
                    && fileObjects.isEmpty()) {
                Option.HELP.process(optionHelper, "-help");
                return Result.CMDERR;
            }

            Collection<File> files;
            try {
                files = processArgs(CommandLine.parse(args), classNames);
                if (files == null) {
                    // null signals an error in options, abort
                    return Result.CMDERR;
                } else if (files.isEmpty() && fileObjects.isEmpty() && classnames.isEmpty()) {
                    // it is allowed to compile nothing if just asking for help or version info
                    if (options.isSet(HELP)
                            || options.isSet(X)
                            || options.isSet(VERSION)
                            || options.isSet(FULLVERSION))
                        return Result.OK;
                    if (JavaCompiler.explicitAnnotationProcessingRequested(options)) {
                        error("err.no.source.files.classes");
                    } else {
                        error("err.no.source.files");
                    }
                    return Result.CMDERR;
                }
            } catch (java.io.FileNotFoundException e) {
                warning("err.file.not.found", e.getMessage());
                return Result.SYSERR;
            }

            boolean forceStdOut = options.isSet("stdout");
            if (forceStdOut) {
                log.flush();
                log.setWriters(new PrintWriter(System.out, true));
            }

            // allow System property in following line as a Mustang legacy
            boolean batchMode = (options.isUnset("nonBatchMode")
                    && System.getProperty("nonBatchMode") == null);
            if (batchMode)
                CacheFSInfo.preRegister(context);

            // FIXME: this code will not be invoked if using JavacTask.parse/analyze/generate
            // invoke any available plugins
            String plugins = options.get(PLUGIN);
            if (plugins != null) {
                JavacProcessingEnvironment pEnv = JavacProcessingEnvironment.instance(context);
                ClassLoader cl = pEnv.getProcessorClassLoader();
                ServiceLoader<Plugin> sl = ServiceLoader.load(Plugin.class, cl);
                Set<List<String>> pluginsToCall = new LinkedHashSet<List<String>>();
                for (String plugin: plugins.split("\\x00")) {
                    pluginsToCall.add(List.from(plugin.split("\\s+")));
                }
                JavacTask task = null;
                Iterator<Plugin> iter = sl.iterator();
                while (iter.hasNext()) {
                    Plugin plugin = iter.next();
                    for (List<String> p: pluginsToCall) {
                        if (plugin.getName().equals(p.head)) {
                            pluginsToCall.remove(p);
                            try {
                                if (task == null)
                                    task = JavacTask.instance(pEnv);
                                plugin.init(task, p.tail.toArray(new String[p.tail.size()]));
                            } catch (Throwable ex) {
                                if (apiMode)
                                    throw new RuntimeException(ex);
                                pluginMessage(ex);
                                return Result.SYSERR;
                            }
                        }
                    }
                }
                for (List<String> p: pluginsToCall) {
                    log.printLines(PrefixKind.JAVAC, "msg.plugin.not.found", p.head);
                }
            }

            comp = JavaCompiler.instance(context);

            // FIXME: this code will not be invoked if using JavacTask.parse/analyze/generate
            String xdoclint = options.get(XDOCLINT);
            String xdoclintCustom = options.get(XDOCLINT_CUSTOM);
            if (xdoclint != null || xdoclintCustom != null) {
                Set<String> doclintOpts = new LinkedHashSet<String>();
                if (xdoclint != null)
                    doclintOpts.add(DocLint.XMSGS_OPTION);
                if (xdoclintCustom != null) {
                    for (String s: xdoclintCustom.split("\\s+")) {
                        if (s.isEmpty())
                            continue;
                        doclintOpts.add(s.replace(XDOCLINT_CUSTOM.text, DocLint.XMSGS_CUSTOM_PREFIX));
                    }
                }
                if (!(doclintOpts.size() == 1
                        && doclintOpts.iterator().next().equals(DocLint.XMSGS_CUSTOM_PREFIX + "none"))) {
                    JavacTask t = BasicJavacTask.instance(context);
                    // standard doclet normally generates H1, H2
                    doclintOpts.add(DocLint.XIMPLICIT_HEADERS + "2");
                    new DocLint().init(t, doclintOpts.toArray(new String[doclintOpts.size()]));
                    comp.keepComments = true;
                }
            }

            fileManager = context.get(JavaFileManager.class);

            if (!files.isEmpty()) {
                // add filenames to fileObjects
                comp = JavaCompiler.instance(context);
                List<JavaFileObject> otherFiles = List.nil();
                JavacFileManager dfm = (JavacFileManager)fileManager;
                for (JavaFileObject fo : dfm.getJavaFileObjectsFromFiles(files))
                    otherFiles = otherFiles.prepend(fo);
                for (JavaFileObject fo : otherFiles)
                    fileObjects = fileObjects.prepend(fo);
            }
            comp.compile(fileObjects,
                    classnames.toList(),
                    processors);

            if (log.expectDiagKeys != null) {
                if (log.expectDiagKeys.isEmpty()) {
                    log.printRawLines("all expected diagnostics found");
                    return Result.OK;
                } else {
                    log.printRawLines("expected diagnostic keys not found: " + log.expectDiagKeys);
                    return Result.ERROR;
                }
            }

            if (comp.errorCount() != 0)
                return Result.ERROR;
        } catch (IOException ex) {
            ioMessage(ex);
            return Result.SYSERR;
        } catch (OutOfMemoryError ex) {
            resourceMessage(ex);
            return Result.SYSERR;
        } catch (StackOverflowError ex) {
            resourceMessage(ex);
            return Result.SYSERR;
        } catch (FatalError ex) {
            feMessage(ex);
            return Result.SYSERR;
        } catch (AnnotationProcessingError ex) {
            if (apiMode)
                throw new RuntimeException(ex.getCause());
            apMessage(ex);
            return Result.SYSERR;
        } catch (ClientCodeException ex) {
            // as specified by javax.tools.JavaCompiler#getTask
            // and javax.tools.JavaCompiler.CompilationTask#call
            throw new RuntimeException(ex.getCause());
        } catch (PropagatedException ex) {
            throw ex.getCause();
        } catch (Throwable ex) {
            // Nasty.  If we've already reported an error, compensate
            // for buggy compiler error recovery by swallowing thrown
            // exceptions.
            if (comp == null || comp.errorCount() == 0 ||
                    options == null || options.isSet("dev"))
                bugMessage(ex);
            return Result.ABNORMAL;
        } finally {
            if (comp != null) {
                try {
                    comp.close();
                } catch (ClientCodeException ex) {
                    throw new RuntimeException(ex.getCause());
                }
            }
            filenames = null;
            options = null;
        }
        return Result.OK;
    }
}
```


2. initProcessAnnotations
3. enterTrees
1. parseFiles

processAnnotations

```java
public class JavaCompiler {
    public void compile(List<JavaFileObject> sourceFileObjects,
                        List<String> classnames,
                        Iterable<? extends Processor> processors) {
        if (processors != null && processors.iterator().hasNext())
            explicitAnnotationProcessingRequested = true;
        // as a JavaCompiler can only be used once, throw an exception if
        // it has been used before.
        if (hasBeenUsed)
            throw new AssertionError("attempt to reuse JavaCompiler");
        hasBeenUsed = true;

        // forcibly set the equivalent of -Xlint:-options, so that no further
        // warnings about command line options are generated from this point on
        options.put(XLINT_CUSTOM.text + "-" + LintCategory.OPTIONS.option, "true");
        options.remove(XLINT_CUSTOM.text + LintCategory.OPTIONS.option);

        start_msec = now();

        try {
            initProcessAnnotations(processors);

            // These method calls must be chained to avoid memory leaks
            delegateCompiler =
                    processAnnotations(
                            enterTrees(stopIfError(CompileState.PARSE, parseFiles(sourceFileObjects))),
                            classnames);

            delegateCompiler.compile2();
            delegateCompiler.close();
            elapsed_msec = delegateCompiler.elapsed_msec;
        } catch (Abort ex) {
            if (devVerbose)
                ex.printStackTrace(System.err);
        } finally {
            if (procEnvImpl != null)
                procEnvImpl.close();
        }
    }

    /**
     * Parses a list of files.
     */
    public List<JCCompilationUnit> parseFiles(Iterable<JavaFileObject> fileObjects) {
        if (shouldStop(CompileState.PARSE))
            return List.nil();

        //parse all files
        ListBuffer<JCCompilationUnit> trees = new ListBuffer<>();
        Set<JavaFileObject> filesSoFar = new HashSet<JavaFileObject>();
        for (JavaFileObject fileObject : fileObjects) {
            if (!filesSoFar.contains(fileObject)) {
                filesSoFar.add(fileObject);
                trees.append(parse(fileObject));
            }
        }
        return trees.toList();
    }
}
```

new Parser and call Parser.parseCompilationUnit

```java
public class JavaCompiler {
    /** Parse contents of file.
     *  @param filename     The name of the file to be parsed.
     */
    public JCTree.JCCompilationUnit parse(JavaFileObject filename) {
        JavaFileObject prev = log.useSource(filename);
        try {
            JCTree.JCCompilationUnit t = parse(filename, readSource(filename));
            if (t.endPositions != null)
                log.setEndPosTable(filename, t.endPositions);
            return t;
        } finally {
            log.useSource(prev);
        }
    }


    /** Parse contents of input stream.
     *  @param filename     The name of the file from which input stream comes.
     *  @param content      The characters to be parsed.
     */
    protected JCCompilationUnit parse(JavaFileObject filename, CharSequence content) {
        long msec = now();
        JCCompilationUnit tree = make.TopLevel(List.<JCTree.JCAnnotation>nil(),
                null, List.<JCTree>nil());
        if (content != null) {
            if (verbose) {
                log.printVerbose("parsing.started", filename);
            }
            if (!taskListener.isEmpty()) {
                TaskEvent e = new TaskEvent(TaskEvent.Kind.PARSE, filename);
                taskListener.started(e);
                keepComments = true;
                genEndPos = true;
            }
            Parser parser = parserFactory.newParser(content, keepComments(), genEndPos, lineDebugInfo);
            tree = parser.parseCompilationUnit();
            if (verbose) {
                log.printVerbose("parsing.done", Long.toString(elapsed(msec)));
            }
        }

        tree.sourcefile = filename;

        if (content != null && !taskListener.isEmpty()) {
            TaskEvent e = new TaskEvent(TaskEvent.Kind.PARSE, tree);
            taskListener.finished(e);
        }

        return tree;
    }

}  
```

call nextToken and do Grammar analysis
```java
public class JavacParser implements Parser {
    /** CompilationUnit = [ { "@" Annotation } PACKAGE Qualident ";"] {ImportDeclaration} {TypeDeclaration}
     */
    public JCTree.JCCompilationUnit parseCompilationUnit() {
        Token firstToken = token;
        JCExpression pid = null;
        JCModifiers mods = null;
        boolean consumedToplevelDoc = false;
        boolean seenImport = false;
        boolean seenPackage = false;
        List<JCAnnotation> packageAnnotations = List.nil();
        if (token.kind == MONKEYS_AT)
            mods = modifiersOpt();

        if (token.kind == PACKAGE) {
            seenPackage = true;
            if (mods != null) {
                checkNoMods(mods.flags);
                packageAnnotations = mods.annotations;
                mods = null;
            }
            nextToken();
            pid = qualident(false);
            accept(SEMI);
        }
        ListBuffer<JCTree> defs = new ListBuffer<JCTree>();
        boolean checkForImports = true;
        boolean firstTypeDecl = true;
        while (token.kind != EOF) {
            if (token.pos > 0 && token.pos <= endPosTable.errorEndPos) {
                // error recovery
                skip(checkForImports, false, false, false);
                if (token.kind == EOF)
                    break;
            }
            if (checkForImports && mods == null && token.kind == IMPORT) {
                seenImport = true;
                defs.append(importDeclaration());
            } else {
                Comment docComment = token.comment(CommentStyle.JAVADOC);
                if (firstTypeDecl && !seenImport && !seenPackage) {
                    docComment = firstToken.comment(CommentStyle.JAVADOC);
                    consumedToplevelDoc = true;
                }
                JCTree def = typeDeclaration(mods, docComment);
                if (def instanceof JCExpressionStatement)
                    def = ((JCExpressionStatement) def).expr;
                defs.append(def);
                if (def instanceof JCClassDecl)
                    checkForImports = false;
                mods = null;
                firstTypeDecl = false;
            }
        }
        JCTree.JCCompilationUnit toplevel = F.at(firstToken.pos).TopLevel(packageAnnotations, pid, defs.toList());
        if (!consumedToplevelDoc)
            attach(toplevel, firstToken.comment(CommentStyle.JAVADOC));
        if (defs.isEmpty())
            storeEnd(toplevel, S.prevToken().endPos);
        if (keepDocComments)
            toplevel.docComments = docComments;
        if (keepLineMap)
            toplevel.lineMap = S.getLineMap();
        this.endPosTable.setParser(null); // remove reference to parser
        toplevel.endPositions = this.endPosTable;
        return toplevel;
    }
}
```

all tokens in `com.sun.tools.javac.parser.Tokens.TokenKind`

see `com.sun.tools.javac.parser.JavaTokenizer.readToken`

## Syntax Analysis

```java
public class TreeMaker implements JCTree.Factory {
    public JCCompilationUnit TopLevel(List<JCAnnotation> packageAnnotations,
                                      JCExpression pid,
                                      List<JCTree> defs) {
        Assert.checkNonNull(packageAnnotations);
        for (JCTree node : defs)
            Assert.check(node instanceof JCClassDecl
                            || node instanceof JCImport
                            || node instanceof JCSkip
                            || node instanceof JCErroneous
                            || (node instanceof JCExpressionStatement
                            && ((JCExpressionStatement) node).expr instanceof JCErroneous),
                    node.getClass().getSimpleName());
        JCCompilationUnit tree = new JCCompilationUnit(packageAnnotations, pid, defs,
                null, null, null, null);
        tree.pos = pos;
        return tree;
    }
}
```



### process
[JSR 269 Maintenance Review](https://jcp.org/aboutJava/communityprocess/maintenance/jsr269/JSR269-MR.html)

Processor


## Semantic Analysis

### desugar

```java
public class JavaCompiler {
    /**
     * Prepare attributed parse trees, in conjunction with their attribution contexts,
     * for source or code generation. If the file was not listed on the command line,
     * the current implicitSourcePolicy is taken into account.
     * The preparation stops as soon as an error is found.
     */
    protected void desugar(final Env<AttrContext> env, Queue<Pair<Env<AttrContext>, JCClassDecl>> results) {
        if (shouldStop(CompileState.TRANSTYPES))
            return;

        if (implicitSourcePolicy == ImplicitSourcePolicy.NONE
                && !inputFiles.contains(env.toplevel.sourcefile)) {
            return;
        }

        if (!modules.multiModuleMode && env.toplevel.modle != modules.getDefaultModule()) {
            //can only generate classfiles for a single module:
            return;
        }

        if (compileStates.isDone(env, CompileState.LOWER)) {
            results.addAll(desugaredEnvs.get(env));
            return;
        }

        /**
         * Ensure that superclasses of C are desugared before C itself. This is
         * required for two reasons: (i) as erasure (TransTypes) destroys
         * information needed in flow analysis and (ii) as some checks carried
         * out during lowering require that all synthetic fields/methods have
         * already been added to C and its superclasses.
         */
        class ScanNested extends TreeScanner {
            Set<Env<AttrContext>> dependencies = new LinkedHashSet<>();
            protected boolean hasLambdas;

            @Override
            public void visitClassDef(JCClassDecl node) {
                Type st = types.supertype(node.sym.type);
                boolean envForSuperTypeFound = false;
                while (!envForSuperTypeFound && st.hasTag(CLASS)) {
                    ClassSymbol c = st.tsym.outermostClass();
                    Env<AttrContext> stEnv = enter.getEnv(c);
                    if (stEnv != null && env != stEnv) {
                        if (dependencies.add(stEnv)) {
                            boolean prevHasLambdas = hasLambdas;
                            try {
                                scan(stEnv.tree);
                            } finally {
                                /*
                                 * ignore any updates to hasLambdas made during
                                 * the nested scan, this ensures an initalized
                                 * LambdaToMethod is available only to those
                                 * classes that contain lambdas
                                 */
                                hasLambdas = prevHasLambdas;
                            }
                        }
                        envForSuperTypeFound = true;
                    }
                    st = types.supertype(st);
                }
                super.visitClassDef(node);
            }

            @Override
            public void visitLambda(JCLambda tree) {
                hasLambdas = true;
                super.visitLambda(tree);
            }

            @Override
            public void visitReference(JCMemberReference tree) {
                hasLambdas = true;
                super.visitReference(tree);
            }
        }
        ScanNested scanner = new ScanNested();
        scanner.scan(env.tree);
        for (Env<AttrContext> dep : scanner.dependencies) {
            if (!compileStates.isDone(dep, CompileState.FLOW))
```
call desugar, flow
```java
                desugaredEnvs.put(dep, desugar(flow(attribute(dep))));
        }

        //We need to check for error another time as more classes might
        //have been attributed and analyzed at this stage
        if (shouldStop(CompileState.TRANSTYPES))
            return;

        if (verboseCompilePolicy)
            printNote("[desugar " + env.enclClass.sym + "]");

        JavaFileObject prev = log.useSource(env.enclClass.sym.sourcefile != null ?
                env.enclClass.sym.sourcefile :
                env.toplevel.sourcefile);
        try {
            //save tree prior to rewriting
            JCTree untranslated = env.tree;

            make.at(Position.FIRSTPOS);
            TreeMaker localMake = make.forToplevel(env.toplevel);

            if (env.tree.hasTag(JCTree.Tag.PACKAGEDEF) || env.tree.hasTag(JCTree.Tag.MODULEDEF)) {
                if (!(sourceOutput)) {
                    if (shouldStop(CompileState.LOWER))
                        return;
                    List<JCTree> def = lower.translateTopLevelClass(env, env.tree, localMake);
                    if (def.head != null) {
                        Assert.check(def.tail.isEmpty());
                        results.add(new Pair<>(env, (JCClassDecl) def.head));
                    }
                }
                return;
            }

            if (shouldStop(CompileState.TRANSTYPES))
                return;

            env.tree = transTypes.translateTopLevelClass(env.tree, localMake);
            compileStates.put(env, CompileState.TRANSTYPES);

            if (Feature.LAMBDA.allowedInSource(source) && scanner.hasLambdas) {
                if (shouldStop(CompileState.UNLAMBDA))
                    return;

                env.tree = LambdaToMethod.instance(context).translateTopLevelClass(env, env.tree, localMake);
                compileStates.put(env, CompileState.UNLAMBDA);
            }

            if (shouldStop(CompileState.LOWER))
                return;

            if (sourceOutput) {
                //emit standard Java source file, only for compilation
                //units enumerated explicitly on the command line
                JCClassDecl cdef = (JCClassDecl) env.tree;
                if (untranslated instanceof JCClassDecl &&
                        rootClasses.contains((JCClassDecl) untranslated)) {
                    results.add(new Pair<>(env, cdef));
                }
                return;
            }

            //translate out inner classes
            List<JCTree> cdefs = lower.translateTopLevelClass(env, env.tree, localMake);
            compileStates.put(env, CompileState.LOWER);

            if (shouldStop(CompileState.LOWER))
                return;

            //generate code for each class
            for (List<JCTree> l = cdefs; l.nonEmpty(); l = l.tail) {
                JCClassDecl cdef = (JCClassDecl) l.head;
                results.add(new Pair<>(env, cdef));
            }
        } finally {
            log.useSource(prev);
        }

    }
}
```

Perform dataflow checks on attributed parse trees.
These include checks for definite assignment and unreachable statements.
If any errors occur, an empty list will be returned.

```java
// JavaCompiler
public Queue<Env<AttrContext>> flow(Queue<Env<AttrContext>> envs) {
        ListBuffer<Env<AttrContext>> results = new ListBuffer<>();
        for (Env<AttrContext> env: envs) {
        flow(env, results);
        }
        return stopIfError(CompileState.FLOW, results);
}
```
#### Type erasure
```java
public class TransTypes extends TreeTranslator {
    private Type erasure(Type t) {
        return types.erasure(t);
    }
}

public class Types {

    // <editor-fold defaultstate="collapsed" desc="erasure">

    /**
     * The erasure of t {@code |t|} -- the type that results when all
     * type parameters in t are deleted.
     */
    public Type erasure(Type t) {
        return eraseNotNeeded(t) ? t : erasure(t, false);
    }

    private Type erasure(Type t, boolean recurse) {
        if (t.isPrimitive())
            return t; /* fast special case */
        else
            return erasure.visit(t, recurse);
    }
}
```


## Generate Byte Code
```java
// This pass maps flat Java (i.e. without inner classes) to bytecodes.
public class Gen extends JCTree.Visitor {
    
}
```


## References
