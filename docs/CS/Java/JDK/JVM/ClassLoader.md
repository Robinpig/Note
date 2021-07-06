# ClassLoader



## ClassLoader



| ClassLoader            | Lang | Load path           | Ext                            |      |
| ---------------------- | ---- | ------------------- | ------------------------------ | ---- |
| `BootstrapClassLoader` | C++  | <JAVA_HOME>/lib     |                                |      |
| `ExtensionClassLoader` | Java | <JAVA_HOME>/lib/ext |                                |      |
| `AppClassLoader`       | Java | classpath/          | extends `ExtensionClassLoader` |      |
| `User ClassLoader`     | Java | all                 | extends `AppClassLoader`       |      |





### 双亲委派

1. 防止重复加载 
2. Java核心API不被篡改 
重写loadClass方法绕过双亲委托
3. 使用组合方式进行加载而非继承

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



#### InstanceKlass::allocate_instance_klass

```cpp
// instanceKlass.cpp
InstanceKlass* InstanceKlass::allocate_instance_klass(const ClassFileParser& parser, TRAPS) {
  const int size = InstanceKlass::size(parser.vtable_size(),
                                       parser.itable_size(),
                                       nonstatic_oop_map_size(parser.total_oop_map_count()),
                                       parser.is_interface(),
                                       parser.is_unsafe_anonymous(),
                                       should_store_fingerprint(parser.is_unsafe_anonymous()));

  const Symbol* const class_name = parser.class_name();
  assert(class_name != NULL, "invariant");
  ClassLoaderData* loader_data = parser.loader_data();
  assert(loader_data != NULL, "invariant");

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

  // Check for pending exception before adding to the loader data and incrementing
  // class count.  Can get OOM here.
  if (HAS_PENDING_EXCEPTION) {
    return NULL;
  }

  return ik;
}
```



#### ClassFileParser::fill_instance_klass



java_lang_Class::create_mirror

```cpp
void ClassFileParser::fill_instance_klass(InstanceKlass* ik, bool changed_by_loadhook, TRAPS) {
  assert(ik != NULL, "invariant");

  // Set name and CLD before adding to CLD
  ik->set_class_loader_data(_loader_data);
  ik->set_name(_class_name);

  // Add all classes to our internal class loader list here,
  // including classes in the bootstrap (NULL) class loader.
  const bool publicize = !is_internal();

  _loader_data->add_class(ik, publicize);

  set_klass_to_deallocate(ik);

  assert(_field_info != NULL, "invariant");
  assert(ik->static_field_size() == _field_info->static_field_size, "sanity");
  assert(ik->nonstatic_oop_map_count() == _field_info->total_oop_map_count,
    "sanity");

  assert(ik->is_instance_klass(), "sanity");
  assert(ik->size_helper() == _field_info->instance_size, "sanity");

  // Fill in information already parsed
  ik->set_should_verify_class(_need_verify);

  // Not yet: supers are done below to support the new subtype-checking fields
  ik->set_nonstatic_field_size(_field_info->nonstatic_field_size);
  ik->set_has_nonstatic_fields(_field_info->has_nonstatic_fields);
  assert(_fac != NULL, "invariant");
  ik->set_static_oop_field_count(_fac->count[STATIC_OOP]);

  // this transfers ownership of a lot of arrays from
  // the parser onto the InstanceKlass*
  apply_parsed_class_metadata(ik, _java_fields_count, CHECK);

  // note that is not safe to use the fields in the parser from this point on
  assert(NULL == _cp, "invariant");
  assert(NULL == _fields, "invariant");
  assert(NULL == _methods, "invariant");
  assert(NULL == _inner_classes, "invariant");
  assert(NULL == _nest_members, "invariant");
  assert(NULL == _local_interfaces, "invariant");
  assert(NULL == _combined_annotations, "invariant");

  if (_has_final_method) {
    ik->set_has_final_method();
  }

  ik->copy_method_ordering(_method_ordering, CHECK);
  // The InstanceKlass::_methods_jmethod_ids cache
  // is managed on the assumption that the initial cache
  // size is equal to the number of methods in the class. If
  // that changes, then InstanceKlass::idnum_can_increment()
  // has to be changed accordingly.
  ik->set_initial_method_idnum(ik->methods()->length());

  ik->set_this_class_index(_this_class_index);

  if (is_unsafe_anonymous()) {
    // _this_class_index is a CONSTANT_Class entry that refers to this
    // anonymous class itself. If this class needs to refer to its own methods or
    // fields, it would use a CONSTANT_MethodRef, etc, which would reference
    // _this_class_index. However, because this class is anonymous (it's
    // not stored in SystemDictionary), _this_class_index cannot be resolved
    // with ConstantPool::klass_at_impl, which does a SystemDictionary lookup.
    // Therefore, we must eagerly resolve _this_class_index now.
    ik->constants()->klass_at_put(_this_class_index, ik);
  }

  ik->set_minor_version(_minor_version);
  ik->set_major_version(_major_version);
  ik->set_has_nonstatic_concrete_methods(_has_nonstatic_concrete_methods);
  ik->set_declares_nonstatic_concrete_methods(_declares_nonstatic_concrete_methods);

  if (_unsafe_anonymous_host != NULL) {
    assert (ik->is_unsafe_anonymous(), "should be the same");
    ik->set_unsafe_anonymous_host(_unsafe_anonymous_host);
  }

  // Set PackageEntry for this_klass
  oop cl = ik->class_loader();
  Handle clh = Handle(THREAD, java_lang_ClassLoader::non_reflection_class_loader(cl));
  ClassLoaderData* cld = ClassLoaderData::class_loader_data_or_null(clh());
  ik->set_package(cld, CHECK);

  const Array<Method*>* const methods = ik->methods();
  assert(methods != NULL, "invariant");
  const int methods_len = methods->length();

  check_methods_for_intrinsics(ik, methods);

  // Fill in field values obtained by parse_classfile_attributes
  if (_parsed_annotations->has_any_annotations()) {
    _parsed_annotations->apply_to(ik);
  }

  apply_parsed_class_attributes(ik);

  // Miranda methods
  if ((_num_miranda_methods > 0) ||
      // if this class introduced new miranda methods or
      (_super_klass != NULL && _super_klass->has_miranda_methods())
        // super class exists and this class inherited miranda methods
     ) {
       ik->set_has_miranda_methods(); // then set a flag
  }

  // Fill in information needed to compute superclasses.
  ik->initialize_supers(const_cast<InstanceKlass*>(_super_klass), _transitive_interfaces, CHECK);
  ik->set_transitive_interfaces(_transitive_interfaces);
  _transitive_interfaces = NULL;

  // Initialize itable offset tables
  klassItable::setup_itable_offset_table(ik);

  // Compute transitive closure of interfaces this class implements
  // Do final class setup
  fill_oop_maps(ik,
                _field_info->nonstatic_oop_map_count,
                _field_info->nonstatic_oop_offsets,
                _field_info->nonstatic_oop_counts);

  // Fill in has_finalizer, has_vanilla_constructor, and layout_helper
  set_precomputed_flags(ik);

  // check if this class can access its super class
  check_super_class_access(ik, CHECK);

  // check if this class can access its superinterfaces
  check_super_interface_access(ik, CHECK);

  // check if this class overrides any final method
  check_final_method_override(ik, CHECK);

  // reject static interface methods prior to Java 8
  if (ik->is_interface() && _major_version < JAVA_8_VERSION) {
    check_illegal_static_method(ik, CHECK);
  }

  // Obtain this_klass' module entry
  ModuleEntry* module_entry = ik->module();
  assert(module_entry != NULL, "module_entry should always be set");

  // Obtain java.lang.Module
  Handle module_handle(THREAD, module_entry->module());

  // Allocate mirror and initialize static fields
  // The create_mirror() call will also call compute_modifiers()
  java_lang_Class::create_mirror(ik,
                                 Handle(THREAD, _loader_data->class_loader()),
                                 module_handle,
                                 _protection_domain,
                                 CHECK);

  assert(_all_mirandas != NULL, "invariant");

  // Generate any default methods - default methods are public interface methods
  // that have a default implementation.  This is new with Java 8.
  if (_has_nonstatic_concrete_methods) {
    DefaultMethods::generate_default_methods(ik,
                                             _all_mirandas,
                                             CHECK);
  }

  // Add read edges to the unnamed modules of the bootstrap and app class loaders.
  if (changed_by_loadhook && !module_handle.is_null() && module_entry->is_named() &&
      !module_entry->has_default_read_edges()) {
    if (!module_entry->set_has_default_read_edges()) {
      // We won a potential race
      JvmtiExport::add_default_read_edges(module_handle, THREAD);
    }
  }

  ClassLoadingService::notify_class_loaded(ik, false /* not shared class */);

  if (!is_internal()) {
    if (log_is_enabled(Info, class, load)) {
      ResourceMark rm;
      const char* module_name = (module_entry->name() == NULL) ? UNNAMED_MODULE : module_entry->name()->as_C_string();
      ik->print_class_load_logging(_loader_data, module_name, _stream);
    }

    if (ik->minor_version() == JAVA_PREVIEW_MINOR_VERSION &&
        ik->major_version() != JAVA_MIN_SUPPORTED_VERSION &&
        log_is_enabled(Info, class, preview)) {
      ResourceMark rm;
      log_info(class, preview)("Loading class %s that depends on preview features (class file version %d.65535)",
                               ik->external_name(), ik->major_version());
    }

    if (log_is_enabled(Debug, class, resolve))  {
      ResourceMark rm;
      // print out the superclass.
      const char * from = ik->external_name();
      if (ik->java_super() != NULL) {
        log_debug(class, resolve)("%s %s (super)",
                   from,
                   ik->java_super()->external_name());
      }
      // print out each of the interface classes referred to by this class.
      const Array<InstanceKlass*>* const local_interfaces = ik->local_interfaces();
      if (local_interfaces != NULL) {
        const int length = local_interfaces->length();
        for (int i = 0; i < length; i++) {
          const InstanceKlass* const k = local_interfaces->at(i);
          const char * to = k->external_name();
          log_debug(class, resolve)("%s %s (interface)", from, to);
        }
      }
    }
  }

  JFR_ONLY(INIT_ID(ik);)

  // If we reach here, all is well.
  // Now remove the InstanceKlass* from the _klass_to_deallocate field
  // in order for it to not be destroyed in the ClassFileParser destructor.
  set_klass_to_deallocate(NULL);

  // it's official
  set_klass(ik);

  debug_only(ik->verify();)
}
```



#### java_lang_Class::create_mirror

```cpp
// javaClasses.cpp
void java_lang_Class::create_mirror(Klass* k, Handle class_loader,
                                    Handle module, Handle protection_domain, TRAPS) {
  assert(k != NULL, "Use create_basic_type_mirror for primitive types");
  assert(k->java_mirror() == NULL, "should only assign mirror once");

  // Use this moment of initialization to cache modifier_flags also,
  // to support Class.getModifiers().  Instance classes recalculate
  // the cached flags after the class file is parsed, but before the
  // class is put into the system dictionary.
  int computed_modifiers = k->compute_modifier_flags(CHECK);
  k->set_modifier_flags(computed_modifiers);
  // Class_klass has to be loaded because it is used to allocate
  // the mirror.
  if (SystemDictionary::Class_klass_loaded()) {
    // Allocate mirror (java.lang.Class instance)
    oop mirror_oop = InstanceMirrorKlass::cast(SystemDictionary::Class_klass())->allocate_instance(k, CHECK);
    Handle mirror(THREAD, mirror_oop);
    Handle comp_mirror;

    // Setup indirection from mirror->klass
    java_lang_Class::set_klass(mirror(), k);

    InstanceMirrorKlass* mk = InstanceMirrorKlass::cast(mirror->klass());
    assert(oop_size(mirror()) == mk->instance_size(k), "should have been set");

    java_lang_Class::set_static_oop_field_count(mirror(), mk->compute_static_oop_field_count(mirror()));

    // It might also have a component mirror.  This mirror must already exist.
    if (k->is_array_klass()) {
      if (k->is_typeArray_klass()) {
        BasicType type = TypeArrayKlass::cast(k)->element_type();
        comp_mirror = Handle(THREAD, Universe::java_mirror(type));
      } else {
        assert(k->is_objArray_klass(), "Must be");
        Klass* element_klass = ObjArrayKlass::cast(k)->element_klass();
        assert(element_klass != NULL, "Must have an element klass");
        comp_mirror = Handle(THREAD, element_klass->java_mirror());
      }
      assert(comp_mirror() != NULL, "must have a mirror");

      // Two-way link between the array klass and its component mirror:
      // (array_klass) k -> mirror -> component_mirror -> array_klass -> k
      set_component_mirror(mirror(), comp_mirror());
      // See below for ordering dependencies between field array_klass in component mirror
      // and java_mirror in this klass.
    } else {
      assert(k->is_instance_klass(), "Must be");

      initialize_mirror_fields(k, mirror, protection_domain, THREAD);
      if (HAS_PENDING_EXCEPTION) {
        // If any of the fields throws an exception like OOM remove the klass field
        // from the mirror so GC doesn't follow it after the klass has been deallocated.
        // This mirror looks like a primitive type, which logically it is because it
        // it represents no class.
        java_lang_Class::set_klass(mirror(), NULL);
        return;
      }
    }

    // set the classLoader field in the java_lang_Class instance
    assert(oopDesc::equals(class_loader(), k->class_loader()), "should be same");
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
  } else {
    assert(fixup_mirror_list() != NULL, "fixup_mirror_list not initialized");
    fixup_mirror_list()->push(k);
  }
}
```



#### InstanceKlass::allocate_instance

todo **Universe::heap()->obj_allocate**

```cpp
instanceOop InstanceKlass::allocate_instance(TRAPS) {
  bool has_finalizer_flag = has_finalizer(); // Query before possible GC
  int size = size_helper();  // Query before forming handle.

  instanceOop i;

  i = (instanceOop)Universe::heap()->obj_allocate(this, size, CHECK_NULL);
  if (has_finalizer_flag && !RegisterFinalizersAtInit) {
    i = register_finalizer(i, CHECK_NULL);
  }
  return i;
}
```



### Linking

InstanceKlass::link_class_impl()


classfile/rewriter.cpp


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

init when use `putstatic`,`getstatic`,`new`,`invokestatic`

InstanceKlass::Initialize_impl()

<clinit>

### Using



### Unloading

use ClassLoaderDataGraph::classed_do can iterate all loaded class when GC
