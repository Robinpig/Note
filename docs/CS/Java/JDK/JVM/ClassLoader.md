## Introduction



| ClassLoader            | Languages | Load path           | Parent                   | JDK11                                                     |
| ---------------------- | --------- | ------------------- | ------------------------ | --------------------------------------------------------- |
| `BootstrapClassLoader` | C++       | <JAVA_HOME>/lib     |                          |                                                           |
| `ExtensionClassLoader` | Java      | <JAVA_HOME>/lib/ext | `BootstrapClassLoader`   | rename to PlatformClassLoader, not extends URLClassLoader |
| `AppClassLoader`       | Java      | classpath/          | `ExtensionClassLoader`   | not extends URLClassLoader                                |
| `User ClassLoader`     | Java      | all                 | default `AppClassLoader` |                                                           |



### Delegation model

The ClassLoader class uses a **delegation model** to search for classes and resources. **Each instance of ClassLoader has an associated parent class loader.** When requested to find a class or resource, a ClassLoader instance will delegate the search for the class or resource to its parent class loader before attempting to find the class or resource itself. The virtual machine's built-in class loader, called the "bootstrap class loader", does not itself have a parent but may serve as the parent of a ClassLoader instance.



加载时机

1. 使用 new 关键字实例化对象的时候、读取或设置一个类的静态字段（被final修饰、已在编译期把结果放入常量池的静态字段除外）的时候，以及调用一个类的静态方法的时候。
2. 使用 java.lang.reflect 包的方法对类进行反射调用的时候，如果类没有进行过初始化，则需要先触发其初始化。
3. 当初始化一个类的时候，如果发现其父类还没有进行过初始化，则需要先触发其父类的初始化。
4. 当虚拟机启动时，用户需要指定一个要执行的主类（包含 main()方法的那个类），虚拟机会先初始化这个主类。
5. 当使用 JDK 1.7 的动态语言支持时，如果一个 java.lang.invoke.MethodHandle 实例最后的解析结果 REF_getStatic、REF_putStatic、REF_invokeStatic 的方法句柄，并且这个方法句柄所对应的类没有进行过初始化，则需要先触发其初始化。



### Parallel

Class loaders that support concurrent loading of classes are known as parallel capable class loaders and are required to register themselves at their class initialization time by invoking the ClassLoader.registerAsParallelCapable method. Note that the ClassLoader class is registered as parallel capable by default. However, its subclasses still need to register themselves if they are parallel capable. In environments in which the delegation model is not strictly hierarchical, class loaders need to be parallel capable, otherwise class loading can lead to deadlocks because the loader lock is held for the duration of the class loading process (see loadClass methods).

In environments in which the delegation model is not strictly hierarchical, class loaders need to be parallel capable, otherwise class loading can lead to deadlocks because the loader lock is held for the duration of the class loading process (see `loadClass` methods).



Loads the class with the specified binary name. The default implementation of this method searches for classes in the following order:

1. Invoke findLoadedClass(String) to check if the class has already been loaded.
2. **Invoke the loadClass method on the parent class loader.** If the parent is null the class loader built-in to the virtual machine is used, instead.
3. Invoke the findClass(String) method to find the class.

If the class was found using the above steps, and the resolve flag is true, this method will then invoke the resolveClass(Class) method on the resulting Class object.
Subclasses of ClassLoader are encouraged to override findClass(String), rather than this method.
Unless overridden, this method synchronizes on the result of getClassLoadingLock method during the entire class loading process.

```java
protected Class<?> loadClass(String name, boolean resolve)
    throws ClassNotFoundException
{
    synchronized (getClassLoadingLock(name)) {
        // First, check if the class has already been loaded
        Class<?> c = findLoadedClass(name);
        if (c == null) {
            long t0 = System.nanoTime();
            try {
                if (parent != null) {
                    c = parent.loadClass(name, false);
                } else {
                    c = findBootstrapClassOrNull(name);
                }
            } catch (ClassNotFoundException e) {
                // ClassNotFoundException thrown if class not found
                // from the non-null parent class loader
            }

            if (c == null) {
                // If still not found, then invoke findClass in order
                // to find the class.
                long t1 = System.nanoTime();
                c = findClass(name);

                // this is the defining class loader; record the stats
                sun.misc.PerfCounter.getParentDelegationTime().addTime(t1 - t0);
                sun.misc.PerfCounter.getFindClassTime().addElapsedTimeFrom(t1);
                sun.misc.PerfCounter.getFindClasses().increment();
            }
        }
        if (resolve) {
            resolveClass(c);
        }
        return c;
    }
}
```



Returns the lock object for class loading operations. For backward compatibility, the default implementation of this method behaves as follows. 

1. If this ClassLoader object is registered as parallel capable, the method returns **a dedicated object associated with the specified class name**. 
2. Otherwise, the method returns **this ClassLoader object**.

```java
protected Object getClassLoadingLock(String className) {
    Object lock = this;
    if (parallelLockMap != null) {
        Object newLock = new Object();
        lock = parallelLockMap.putIfAbsent(className, newLock);
        if (lock == null) {
            lock = newLock;
        }
    }
    return lock;
}

// Maps class name to the corresponding lock object when the current
// class loader is parallel capable.
// Note: VM also uses this field to decide if the current class loader
// is parallel capable and the appropriate lock object for class loading.
private final ConcurrentHashMap<String, Object> parallelLockMap;
```



#### Destroy delegate model

1. override loadClass(), not findClass()
2. SPI, JDBC JNDI,use contextClassLoader(most be ApplicationClassLoader)
3. hotswap, `OSGI`(`Open Service Gateway Initiative`), Tomcat WebApplicationClassLoader or Spring devtools RestartClassLoader
4. since JDK9, module 



### load source

Normally, the Java virtual machine loads classes from the local file system in a platform-dependent manner. For example, on UNIX systems, the virtual machine loads classes from the directory defined by the CLASSPATH environment variable.
However, some classes may not originate from a file; they may originate from other sources, such as the network, or they could be constructed by an application. The method defineClass converts an array of bytes into an instance of class Class. Instances of this newly defined class can be created using Class.newInstance.
The methods and constructors of objects created by a class loader may reference other classes. To determine the class(es) referred to, the Java virtual machine invokes the loadClass method of the class loader that originally created the class.

For example, an application could create a network class loader to download class files from a server. Sample code might look like:

```java
     ClassLoader loader = new NetworkClassLoader(host, port);
     Object main = loader.loadClass("Main", true).newInstance();
          . . .
```

The network class loader subclass must define the methods findClass and loadClassData to load a class from the network. Once it has downloaded the bytes that make up the class, it should use the method defineClass to create a class instance. 
A sample implementation is:

```java
       class NetworkClassLoader extends ClassLoader {
           String host;
           int port;

           public Class findClass(String name) {
               byte[] b = loadClassData(name);
               return defineClass(name, b, 0, b.length);
           }
      
           private byte[] loadClassData(String name) {
               // load the class data from the connection
                . . .
           }
       }
```



### User ClassLoader Sample

Creates a new class loader using the ClassLoader returned by the method getSystemClassLoader() as the parent class loader.
If there is a security manager, its checkCreateClassLoader method is invoked. This may result in a security exception.

```java
// ClassLoader
protected ClassLoader() {
    this(checkCreateClassLoader(), getSystemClassLoader());
}
```

```shell
-XX:+TraceClassLoading
-Xlog: class+load=info # JDK11
```







## Load Class

![Screen Shot 2021-08-03 at 7.24.58 AM](/Users/robin/Desktop/Screen Shot 2021-08-03 at 7.24.58 AM.png)

ClassLoader::load_class();

ClassLoaderData

1. Loading
2. Linking
   1. Verification
   2. Preparation
   3. Resolution
3. Initialization
4. Using
5. Unloading

### Loading

负责从文件系统或者网络中加载Class文件，Class文件开头有特定Magic Number ， 4Byte

Classloader只负责class文件的加载，至于是否可运行，则由执行引擎决定

加载的类信息存放于称为方法区的内存空间，除了类信息，方法区还会存放运行时常量池信息，还可能包括字符串字面量和数字常量

常量池运行时加载到内存中，即运行时常量池

1. 通过一个类的全限定名获取定义此类的二进制字节流
   1. 本地系统获取网络获取，
   2. Web Appletzip压缩包获取，jar，war
   3. 运行时计算生成，
   4. 动态代理有其他文件生成，
   5. jsp专有数据库提取.class文件，
   6. 比较少见加密文件中获取，防止Class文件被反编译的保护措施
2. 将这个字节流所代表的的静态存储结果转化为方法区的运行时数据结构
3. 在内存中生成一个代表这个类的java.lang.Class对象，作为方法区这个类的各种数据访问入口



Loads the class with the specified binary name. The default implementation of this method searches for classes in the following order:
1. Invoke findLoadedClass(String) to check if the class has already been loaded.
2. Invoke the loadClass method on the parent class loader. If the parent is null the class loader built-in to the virtual machine is used, instead.
3. Invoke the findClass(String) method to find the class.

If the class was found using the above steps, and the resolve flag is true, this method will then invoke the resolveClass(Class) method on the resulting Class object.
Subclasses of ClassLoader are encouraged to override findClass(String), rather than this method.
Unless overridden, this method synchronizes on the result of getClassLoadingLock method during the entire class loading process.

```java
protected Class<?> loadClass(String name, boolean resolve)
        throws ClassNotFoundException
    {
        synchronized (getClassLoadingLock(name)) {
            // First, check if the class has already been loaded
            Class<?> c = findLoadedClass(name);
if (c == null) {
long t0 = System.nanoTime();
try {
if (parent != null) {
c = parent.loadClass(name, false);
} else {
c = findBootstrapClassOrNull(name);
}
} catch (ClassNotFoundException e) {
// ClassNotFoundException thrown if class not found
// from the non-null parent class loader
}

                if (c == null) {
                    // If still not found, then invoke findClass in order
                    // to find the class.
                    long t1 = System.nanoTime();
                    c = findClass(name);

                    // this is the defining class loader; record the stats
                    sun.misc.PerfCounter.getParentDelegationTime().addTime(t1 - t0);
                    sun.misc.PerfCounter.getFindClassTime().addElapsedTimeFrom(t1);
                    sun.misc.PerfCounter.getFindClasses().increment();
                }
            }
            if (resolve) {
                resolveClass(c);
            }
            return c;
        }
    }

protected Object getClassLoadingLock(String className) {
        Object lock = this;
        if (parallelLockMap != null) {
        Object newLock = new Object();
        lock = parallelLockMap.putIfAbsent(className, newLock);
        if (lock == null) {
        lock = newLock;
        }
        }
        return lock;
        }
```



*Links the specified class. This (misleadingly named) method may be used by a class loader to link a class. If the class c has already been linked, then this method simply returns. Otherwise, the class is linked as described in the "Execution" chapter of The Java™ Language Specification.*

```java
protected final void resolveClass(Class<?> c) {
        resolveClass0(c);
    }
    
private native void resolveClass0(Class<?> c);
```






```cpp
//classLoader.cpp
// Called by the boot classloader to load classes
InstanceKlass* ClassLoader::load_class(Symbol* name, bool search_append_only, TRAPS) {
	...

  InstanceKlass* result = KlassFactory::create_from_stream(stream, name,
                                                           loader_data, cl_info, CHECK_NULL);
  result->set_classpath_index(classpath_index);
  return result;
}
```



or

#### Java_java_lang_ClassLoader_defineClass1

defineClass2 also call  `JVM_DefineClassWithSource`

```c
// ClassLoader.c
JNIEXPORT jclass JNICALL
Java_java_lang_ClassLoader_defineClass1(JNIEnv *env, jclass cls, jobject loader,
                                        jstring name, jbyteArray data, jint offset,
                                        jint length, jobject pd, jstring source)
{

    jclass result = 0;
    ...
    result = JVM_DefineClassWithSource(env, utfName, loader, body, length, pd, utfSource);
		...
    return result;
}
```



call `SystemDictionary::resolve_from_stream`

```cpp
// jvm.cpp
JVM_ENTRY(jclass, JVM_DefineClassWithSource(JNIEnv *env, const char *name, jobject loader, const jbyte *buf, jsize len, jobject pd, const char *source))
  JVMWrapper("JVM_DefineClassWithSource");

  return jvm_define_class_common(env, name, loader, buf, len, pd, source, THREAD);
JVM_END
```





```cpp
// common code for JVM_DefineClass() and JVM_DefineClassWithSource()
static jclass jvm_define_class_common(JNIEnv *env, const char *name,
                                      jobject loader, const jbyte *buf,
                                      jsize len, jobject pd, const char *source,
                                      TRAPS) {



  Handle class_loader (THREAD, JNIHandles::resolve(loader));
  
  Handle protection_domain (THREAD, JNIHandles::resolve(pd));
  
  Klass* k = SystemDictionary::resolve_from_stream(class_name,
                                                   class_loader,
                                                   protection_domain,
                                                   &st,
                                                   CHECK_NULL);

  return (jclass) JNIHandles::make_local(env, k->java_mirror());
}
```





```cpp
// systemDictionary.cpp
// Add a klass to the system from a stream (called by jni_DefineClass and
// JVM_DefineClass).
// Note: class_name can be NULL. In that case we do not know the name of
// the class until we have parsed the stream.

InstanceKlass* SystemDictionary::resolve_from_stream(Symbol* class_name,
                                                     Handle class_loader,
                                                     Handle protection_domain,
                                                     ClassFileStream* st,
                                                     TRAPS) {

  
  ClassLoaderData* loader_data = register_loader(class_loader);

  
  // Parse the stream and create a klass.
  // Note that we do this even though this klass might
  // already be present in the SystemDictionary, otherwise we would not
  // throw potential ClassFormatErrors.
 InstanceKlass* k = NULL;

#if INCLUDE_CDS
  if (!DumpSharedSpaces) {
    k = SystemDictionaryShared::lookup_from_stream(class_name, class_loader,
                                                   protection_domain, st, CHECK_NULL);
  }
#endif

    k = KlassFactory::create_from_stream(st, class_name, loader_data, protection_domain,
                                         NULL, // unsafe_anonymous_host
                                         NULL, // cp_patches
                                         CHECK_NULL);
  ...
  return k;
}
```




```cpp
//klassFactory.cpp
InstanceKlass* KlassFactory::create_from_stream(ClassFileStream* stream,
                                                Symbol* name,
                                                ClassLoaderData* loader_data,
                                                const ClassLoadInfo& cl_info,
                                                TRAPS) {
	...

  // Skip this processing for VM hidden classes
  if (!cl_info.is_hidden()) {
    stream = check_class_file_load_hook(stream, name, loader_data, cl_info.protection_domain(),
                                        &cached_class_file, CHECK_NULL);
  }
  
  // parse stream
  ClassFileParser parser(stream, name, loader_data, &cl_info,
                         ClassFileParser::BROADCAST, // publicity level
                         CHECK_NULL);
	
  // create_instance_klass
  InstanceKlass* result = parser.create_instance_klass(old_stream != stream, *cl_inst_info, CHECK_NULL);

  return result;
}
```



```cpp
ClassFileParser::ClassFileParser(...) {
	...

  parse_stream(stream, CHECK);

  post_process_parsed_stream(stream, _cp, CHECK);
}
```

#### ClassFileParser::parse_stream 

```cpp
//classFileParser.cpp
void ClassFileParser::parse_stream(const ClassFileStream* const stream,
                                   TRAPS) {
  // verify

  _cp = ConstantPool::allocate(_loader_data, cp_size, CHECK);
  ConstantPool* const cp = _cp;
  parse_constant_pool(stream, cp, _orig_cp_size, CHECK);
  
  ...

  // SUPERKLASS
  _super_class_index = stream->get_u2_fast();
  _super_klass = parse_super_class(cp, _super_class_index, _need_verify, CHECK);

  // Interfaces
  _itfs_len = stream->get_u2_fast();
  parse_interfaces(stream,
                   _itfs_len,
                   cp,
                   &_has_nonstatic_concrete_methods,
                   CHECK);

  // Fields (offsets are filled in later)
  _fac = new FieldAllocationCount();
  parse_fields(stream,
               _access_flags.is_interface(),
               _fac,
               cp,
               cp_size,
               &_java_fields_count,
               CHECK);

  // Methods
  AccessFlags promoted_flags;
  parse_methods(stream,
                _access_flags.is_interface(),
                &promoted_flags,
                &_has_final_method,
                &_declares_nonstatic_concrete_methods,
                CHECK);

 ...

  // Additional attributes/annotations
  _parsed_annotations = new ClassAnnotationCollector();
  parse_classfile_attributes(stream, cp, _parsed_annotations, CHECK);

  // Finalize the Annotations metadata object,
  // now that all annotation arrays have been created.
  create_combined_annotations(CHECK);
}
```



#### ClassFileParser::create_instance_klass

1. InstanceKlass::allocate_instance_klass()
2. fill_instance_klass()

```cpp
//classFileParser.cpp
InstanceKlass* ClassFileParser::create_instance_klass(bool changed_by_loadhook,
                                                      const ClassInstanceInfo& cl_inst_info,
                                                      TRAPS) {
  //_klass not NULL, return

  InstanceKlass* const ik =
    InstanceKlass::allocate_instance_klass(*this, CHECK_NULL);

  if (is_hidden()) {
    mangle_hidden_class_name(ik);
  }

  fill_instance_klass(ik, changed_by_loadhook, cl_inst_info, CHECK_NULL);

  return ik;
}
```



##### InstanceKlass::allocate_instance_klass

```cpp
// instanceKlass.cpp
InstanceKlass* InstanceKlass::allocate_instance_klass(const ClassFileParser& parser, TRAPS) {
  InstanceKlass* ik;

  // Allocation
  if (REF_NONE == parser.reference_type()) {
    if (class_name == vmSymbols::java_lang_Class()) {
      // mirror
      ik = new (loader_data, size, THREAD) InstanceMirrorKlass(parser);
    }
    else if (is_class_loader(class_name, parser)) {
      // class loader
      ik = new (loader_data, size, THREAD) InstanceClassLoaderKlass(parser);
    } else {
      // normal
      ik = new (loader_data, size, THREAD) InstanceKlass(parser, InstanceKlass::_misc_kind_other);
    }
  } else {
    // reference
    ik = new (loader_data, size, THREAD) InstanceRefKlass(parser);
  }
  
  return ik;
}
```



##### ClassFileParser::fill_instance_klass

`java_lang_Class::create_mirror`

```cpp
void ClassFileParser::fill_instance_klass(InstanceKlass* ik, bool changed_by_loadhook, TRAPS) {

  set_klass_to_deallocate(ik);
 
  // Set PackageEntry for this_klass
  oop cl = ik->class_loader();
  Handle clh = Handle(THREAD, java_lang_ClassLoader::non_reflection_class_loader(cl));
  ClassLoaderData* cld = ClassLoaderData::class_loader_data_or_null(clh());
  ik->set_package(cld, CHECK);

  // Allocate mirror and initialize static fields
  // The create_mirror() call will also call compute_modifiers()
  java_lang_Class::create_mirror(ik,
                                 Handle(THREAD, _loader_data->class_loader()),
                                 module_handle,
                                 _protection_domain,
                                 CHECK);


  // Generate any default methods - default methods are public interface methods
  // that have a default implementation.  This is new with Java 8.
  if (_has_nonstatic_concrete_methods) {
    DefaultMethods::generate_default_methods(ik, _all_mirandas, CHECK);
  }

  ClassLoadingService::notify_class_loaded(ik, false /* not shared class */);

  // If we reach here, all is well.
  // Now remove the InstanceKlass* from the _klass_to_deallocate field
  // in order for it to not be destroyed in the ClassFileParser destructor.
  set_klass_to_deallocate(NULL);

  // it's official
  set_klass(ik);
}
```



#### java_lang_Class::create_mirror

```cpp
// javaClasses.cpp
void java_lang_Class::create_mirror(Klass* k, Handle class_loader,
                                    Handle module, Handle protection_domain, TRAPS) {
     
  	initialize_mirror_fields(k, mirror, protection_domain, THREAD);

    // set the classLoader field in the java_lang_Class instance
    set_class_loader(mirror(), class_loader());

    // Setup indirection from klass->mirror
    // after any exceptions can happen during allocations.
    k->set_java_mirror(mirror);

    // Set the module field in the java_lang_Class instance.  This must be done
    // after the mirror is set.
    set_mirror_module_field(k, mirror, module, THREAD);

    if (comp_mirror() != NULL) {
      // Set after k->java_mirror() is published, because compiled code running
      // concurrently doesn't expect a k to have a null java_mirror.
      release_set_array_klass(comp_mirror(), k);
    }
}
```





### Linking

InstanceKlass::link_class_impl()

classfile/rewriter.cpp 

#### rewrite

_return

_lookupswitch






#### Verification

目的

确保Class文件的字节流中包含信息符合当前虚拟机要求，保证被加载类的正确性，不会危害虚拟机自身安全

四种验证

文件格式验证

CA FE BA BE(魔数，Java虚拟机识别)

主次版本号

常量池的常量中是否有不被支持的常量类型

指向常量的各种索引值中是否有指向不存在的常量或不符合类型的常量


classfile/verifier.cpp

#### Preparation

prepare the memory in method area

`ConstantValue` will set the final value

#### Resolution

可以在Initiailzation之后进行

### Initialization

*Initialization* of a class or interface consists of executing its class or interface initialization method



init when use `putstatic`,`getstatic`,`new`,`invokestatic`

InstanceKlass::Initialize_impl()

<clinit>

### Using



### Unloading

```shell
-XX:+ClassUnloading # default true
```



use ClassLoaderDataGraph::classed_do can iterate all loaded class when GC
