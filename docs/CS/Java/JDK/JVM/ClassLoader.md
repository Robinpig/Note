# ClassLoader



## ClassLoader Type

- `BootstrapClassLoader`

  C++实现,

- `ExtensionClassLoader`

- `AppClassLoader`

  继承于Ext类加载器

- User ClassLoader
  
  
  

### 双亲委派

1. 防止重复加载 
2. Java核心API不被篡改 
重写loadClass方法绕过双亲委托

破坏双亲委托

1. override loadClass(), not findClass()
2. SPI机制, JDBC JNDI,use contextClassLoader(most be ApplicationClassLoader)
3. hotswap, `OSGI`(`Open Service Gateway Initiative`) or Spring devtools RestartClassLoader
4. since JDK9, module 



加载时机

1. 使用 new 关键字实例化对象的时候、读取或设置一个类的静态字段（被final修饰、已在编译期把结果放入常量池的静态字段除外）的时候，以及调用一个类的静态方法的时候。
2. 使用 java.lang.reflect 包的方法对类进行反射调用的时候，如果类没有进行过初始化，则需要先触发其初始化。
3. 当初始化一个类的时候，如果发现其父类还没有进行过初始化，则需要先触发其父类的初始化。
4. 当虚拟机启动时，用户需要指定一个要执行的主类（包含 main()方法的那个类），虚拟机会先初始化这个主类。
5. 当使用 JDK 1.7 的动态语言支持时，如果一个 java.lang.invoke.MethodHandle 实例最后的解析结果 REF_getStatic、REF_putStatic、REF_invokeStatic 的方法句柄，并且这个方法句柄所对应的类没有进行过初始化，则需要先触发其初始化。






## Load Class

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

  ResourceMark rm(THREAD);
  HandleMark hm(THREAD);

  const char* const class_name = name->as_C_string();

  EventMark m("loading class %s", class_name);

  const char* const file_name = file_name_for_class_name(class_name,
                                                         name->utf8_length());

  // Lookup stream for parsing .class file
  ClassFileStream* stream = NULL;
  s2 classpath_index = 0;
  ClassPathEntry* e = NULL;

  // If search_append_only is true, boot loader visibility boundaries are
  // set to be _first_append_entry to the end. This includes:
  //   [-Xbootclasspath/a]; [jvmti appended entries]
  //
  // If search_append_only is false, boot loader visibility boundaries are
  // set to be the --patch-module entries plus the base piece. This includes:
  //   [--patch-module=<module>=<file>(<pathsep><file>)*]; [jimage | exploded module build]
  //

  // Load Attempt #1: --patch-module
  // Determine the class' defining module.  If it appears in the _patch_mod_entries,
  // attempt to load the class from those locations specific to the module.
  // Specifications to --patch-module can contain a partial number of classes
  // that are part of the overall module definition.  So if a particular class is not
  // found within its module specification, the search should continue to Load Attempt #2.
  // Note: The --patch-module entries are never searched if the boot loader's
  //       visibility boundary is limited to only searching the append entries.
  if (_patch_mod_entries != NULL && !search_append_only) {
    // At CDS dump time, the --patch-module entries are ignored. That means a
    // class is still loaded from the runtime image even if it might
    // appear in the _patch_mod_entries. The runtime shared class visibility
    // check will determine if a shared class is visible based on the runtime
    // environemnt, including the runtime --patch-module setting.
    //
    // DynamicDumpSharedSpaces requires UseSharedSpaces to be enabled. Since --patch-module
    // is not supported with UseSharedSpaces, it is not supported with DynamicDumpSharedSpaces.
    if (!DumpSharedSpaces) {
      stream = search_module_entries(THREAD, _patch_mod_entries, class_name, file_name);
    }
  }

  // Load Attempt #2: [jimage | exploded build]
  if (!search_append_only && (NULL == stream)) {
    if (has_jrt_entry()) {
      e = _jrt_entry;
      stream = _jrt_entry->open_stream(THREAD, file_name);
    } else {
      // Exploded build - attempt to locate class in its defining module's location.
      stream = search_module_entries(THREAD, _exploded_entries, class_name, file_name);
    }
  }

  // Load Attempt #3: [-Xbootclasspath/a]; [jvmti appended entries]
  if (search_append_only && (NULL == stream)) {
    // For the boot loader append path search, the starting classpath_index
    // for the appended piece is always 1 to account for either the
    // _jrt_entry or the _exploded_entries.
    classpath_index = 1;

    e = first_append_entry();
    while (e != NULL) {
      stream = e->open_stream(THREAD, file_name);
      if (NULL != stream) {
        break;
      }
      e = e->next();
      ++classpath_index;
    }
  }

  if (NULL == stream) {
    return NULL;
  }

  stream->set_verify(ClassLoaderExt::should_verify(classpath_index));

  ClassLoaderData* loader_data = ClassLoaderData::the_null_class_loader_data();
  Handle protection_domain;
  ClassLoadInfo cl_info(protection_domain);

  InstanceKlass* result = KlassFactory::create_from_stream(stream,
                                                           name,
                                                           loader_data,
                                                           cl_info,
                                                           CHECK_NULL);
  result->set_classpath_index(classpath_index);
  return result;
}
```


```cpp
//klassFactory.cpp
InstanceKlass* KlassFactory::create_from_stream(ClassFileStream* stream,
                                                Symbol* name,
                                                ClassLoaderData* loader_data,
                                                const ClassLoadInfo& cl_info,
                                                TRAPS) {
  ResourceMark rm(THREAD);
  HandleMark hm(THREAD);

  JvmtiCachedClassFileData* cached_class_file = NULL;

  ClassFileStream* old_stream = stream;

  // increment counter
  THREAD->statistical_info().incr_define_class_count();

  // Skip this processing for VM hidden classes
  if (!cl_info.is_hidden()) {
    stream = check_class_file_load_hook(stream,
                                        name,
                                        loader_data,
                                        cl_info.protection_domain(),
                                        &cached_class_file,
                                        CHECK_NULL);
  }
  // parse stream
  ClassFileParser parser(stream,
                         name,
                         loader_data,
                         &cl_info,
                         ClassFileParser::BROADCAST, // publicity level
                         CHECK_NULL);

  const ClassInstanceInfo* cl_inst_info = cl_info.class_hidden_info_ptr();
  InstanceKlass* result = parser.create_instance_klass(old_stream != stream, *cl_inst_info, CHECK_NULL);

  if (cached_class_file != NULL) {
    // JVMTI: we have an InstanceKlass now, tell it about the cached bytes
    result->set_cached_class_file(cached_class_file);
  }

  JFR_ONLY(ON_KLASS_CREATION(result, parser, THREAD);)

#if INCLUDE_CDS
  if (Arguments::is_dumping_archive()) {
    ClassLoader::record_result(THREAD, result, stream);
  }
#endif // INCLUDE_CDS

  return result;
}
```



```cpp
//classFileParser.cpp
void ClassFileParser::parse_stream(const ClassFileStream* const stream,
                                   TRAPS) {
  // BEGIN STREAM PARSING
  stream->guarantee_more(8, CHECK);  // magic, major, minor
  // Magic value
  const u4 magic = stream->get_u4_fast();
  guarantee_property(magic == JAVA_CLASSFILE_MAGIC,
                     "Incompatible magic value %u in class file %s",
                     magic, CHECK);

  // Version numbers
  _minor_version = stream->get_u2_fast();
  _major_version = stream->get_u2_fast();

  // Check version numbers - we check this even with verifier off
  verify_class_version(_major_version, _minor_version, _class_name, CHECK);

  stream->guarantee_more(3, CHECK); // length, first cp tag
  u2 cp_size = stream->get_u2_fast();

  guarantee_property(
    cp_size >= 1, "Illegal constant pool size %u in class file %s",
    cp_size, CHECK);

  _orig_cp_size = cp_size;
  if (is_hidden()) { // Add a slot for hidden class name.
    cp_size++;
  }

  _cp = ConstantPool::allocate(_loader_data,
                               cp_size,
                               CHECK);

  ConstantPool* const cp = _cp;

  parse_constant_pool(stream, cp, _orig_cp_size, CHECK);

  // ACCESS FLAGS
  stream->guarantee_more(8, CHECK);  // flags, this_class, super_class, infs_len

  // Access flags
  jint flags;
  // JVM_ACC_MODULE is defined in JDK-9 and later.
  if (_major_version >= JAVA_9_VERSION) {
    flags = stream->get_u2_fast() & (JVM_RECOGNIZED_CLASS_MODIFIERS | JVM_ACC_MODULE);
  } else {
    flags = stream->get_u2_fast() & JVM_RECOGNIZED_CLASS_MODIFIERS;
  }

  if ((flags & JVM_ACC_INTERFACE) && _major_version < JAVA_6_VERSION) {
    // Set abstract bit for old class files for backward compatibility
    flags |= JVM_ACC_ABSTRACT;
  }

  verify_legal_class_modifiers(flags, CHECK);

  short bad_constant = class_bad_constant_seen();
  if (bad_constant != 0) {
    // Do not throw CFE until after the access_flags are checked because if
    // ACC_MODULE is set in the access flags, then NCDFE must be thrown, not CFE.
    classfile_parse_error("Unknown constant tag %u in class file %s", bad_constant, THREAD);
    return;
  }

  _access_flags.set_flags(flags);

  // This class and superclass
  _this_class_index = stream->get_u2_fast();
  check_property(
    valid_cp_range(_this_class_index, cp_size) &&
      cp->tag_at(_this_class_index).is_unresolved_klass(),
    "Invalid this class index %u in constant pool in class file %s",
    _this_class_index, CHECK);

  Symbol* const class_name_in_cp = cp->klass_name_at(_this_class_index);

  // Don't need to check whether this class name is legal or not.
  // It has been checked when constant pool is parsed.
  // However, make sure it is not an array type.
  if (_need_verify) {
    guarantee_property(class_name_in_cp->char_at(0) != JVM_SIGNATURE_ARRAY,
                       "Bad class name in class file %s",
                       CHECK);
  }

#ifdef ASSERT
  // Basic sanity checks
  if (_is_hidden) {
    assert(_class_name != vmSymbols::unknown_class_name(), "hidden classes should have a special name");
  }
#endif

  // Update the _class_name as needed depending on whether this is a named, un-named, or hidden class.

  if (_is_hidden) {
    assert(_class_name != NULL, "Unexpected null _class_name");
#ifdef ASSERT
    if (_need_verify) {
      verify_legal_class_name(_class_name, CHECK);
    }
#endif

  } else {
    // Check if name in class file matches given name
    if (_class_name != class_name_in_cp) {
      if (_class_name != vmSymbols::unknown_class_name()) {
        ResourceMark rm(THREAD);
        Exceptions::fthrow(THREAD_AND_LOCATION,
                           vmSymbols::java_lang_NoClassDefFoundError(),
                           "%s (wrong name: %s)",
                           class_name_in_cp->as_C_string(),
                           _class_name->as_C_string()
                           );
        return;
      } else {
        // The class name was not known by the caller so we set it from
        // the value in the CP.
        update_class_name(class_name_in_cp);
      }
      // else nothing to do: the expected class name matches what is in the CP
    }
  }
  if (!is_internal()) {
    LogTarget(Debug, class, preorder) lt;
    if (lt.is_enabled()){
      ResourceMark rm(THREAD);
      LogStream ls(lt);
      ls.print("%s", _class_name->as_klass_external_name());
      if (stream->source() != NULL) {
        ls.print(" source: %s", stream->source());
      }
      ls.cr();
    }
  }

  // SUPERKLASS
  _super_class_index = stream->get_u2_fast();
  _super_klass = parse_super_class(cp,
                                   _super_class_index,
                                   _need_verify,
                                   CHECK);

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

  // promote flags from parse_methods() to the klass' flags
  _access_flags.add_promoted_flags(promoted_flags.as_int());

  if (_declares_nonstatic_concrete_methods) {
    _has_nonstatic_concrete_methods = true;
  }

  // Additional attributes/annotations
  _parsed_annotations = new ClassAnnotationCollector();
  parse_classfile_attributes(stream, cp, _parsed_annotations, CHECK);

  // Finalize the Annotations metadata object,
  // now that all annotation arrays have been created.
  create_combined_annotations(CHECK);

  // Make sure this is the end of class file stream
  guarantee_property(stream->at_eos(),
                     "Extra bytes at the end of class file %s",
                     CHECK);

  // all bytes in stream read and parsed
}
```

ClassFileParser::create_instance_klass():
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

### Linking

InstanceKlass::link_class_impl()


classfile/rewriter.cpp


### Verification

目的

确保Class文件的字节流中包含信息符合当前虚拟机要求，保证被加载类的正确性，不会危害虚拟机自身安全

四种验证

文件格式验证

CA FE BA BE(魔数，Java虚拟机识别)

主次版本号

常量池的常量中是否有不被支持的常量类型

指向常量的各种索引值中是否有指向不存在的常量或不符合类型的常量


classfile/verifier.cpp

### Preparation

prepare the memory in method area

`ConstantValue` will set the final value

### Resolution



### Initialization

InstanceKlass::Initialize_impl()

<clinit>

### Using



### Unloading

use ClassLoaderDataGraph::classed_do can iterate all loaded class when GC
