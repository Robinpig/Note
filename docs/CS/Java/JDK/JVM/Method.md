## Introduction

HotSpot VM通过Method类保存方法的元信息。Method用来保存方法中的一些常见信息，如运行时的解释入口和编译入口
Method实例表示一个Java方法，因为一个应用有成千上万个方法，所以保证Method类在内存中的布局紧凑非常重要。为了方便回收垃圾，Method把所有的指针变量和方法都放在了Method内存布局的前面”
Java方法本身的不可变数据如字节码等用ConstMethod表示，可变数据如Profile统计的性能数据等用MethodData表示，它们都可以在Method中通过指针访问。
如果是本地方法，Method实例的内存布局的最后是native_function和signature_handler属性，按照解释器的要求，这两个属性必须在固定的偏移处


ConstMethod实例用于保存方法中不可变部分的信息，如方法的字节码和方法参数的大小等



```cpp
class Method : public Metadata {
 friend class VMStructs;
 friend class JVMCIVMStructs;
 friend class MethodTest;
 private:
  // If you add a new field that points to any metaspace object, you
  // must add this field to Method::metaspace_pointers_do().
  ConstMethod*      _constMethod;                // Method read-only data.
  MethodData*       _method_data;
  MethodCounters*   _method_counters;
  AdapterHandlerEntry* _adapter;
  AccessFlags       _access_flags;               // Access flags
  int               _vtable_index;               // vtable index of this method (see VtableIndexFlag)
                                                 // note: can have vtables with >2**16 elements (because of inheritance)
  u2                _intrinsic_id;               // vmSymbols::intrinsic_id (0 == _none)

  // Flags
  enum Flags {
    _caller_sensitive       = 1 << 0,
    _force_inline           = 1 << 1,
    _dont_inline            = 1 << 2,
    _hidden                 = 1 << 3,
    _has_injected_profile   = 1 << 4,
    _intrinsic_candidate    = 1 << 5,
    _reserved_stack_access  = 1 << 6,
    _scoped                 = 1 << 7,
    _changes_current_thread = 1 << 8,
    _jvmti_mount_transition = 1 << 9,
  };
  mutable u2 _flags;

  JFR_ONLY(DEFINE_TRACE_FLAG;)

#ifndef PRODUCT
  int64_t _compiled_invocation_count;

  Symbol* _name;
#endif
  // Entry point for calling both from and to the interpreter.
  address _i2i_entry;           // All-args-on-stack calling convention
  // Entry point for calling from compiled code, to compiled code if it exists
  // or else the interpreter.
  volatile address _from_compiled_entry;        // Cache of: _code ? _code->entry_point() : _adapter->c2i_entry()
  // The entry point for calling both from and to compiled code is
  // "_code->entry_point()".  Because of tiered compilation and de-opt, this
  // field can come and go.  It can transition from NULL to not-null at any
  // time (whenever a compile completes).  It can transition from not-null to
  // NULL only at safepoints (because of a de-opt).
  CompiledMethod* volatile _code;                       // Points to the corresponding piece of native code
  volatile address           _from_interpreted_entry; // Cache of _code ? _adapter->i2c_entry() : _i2i_entry

  // Constructor
  Method(ConstMethod* xconst, AccessFlags access_flags, Symbol* name);
}  
```



```cpp
class ConstMethod : public MetaspaceObj {
  friend class VMStructs;
  friend class JVMCIVMStructs;

public:
  typedef enum { NORMAL, OVERPASS } MethodType;

private:

  // Bit vector of signature
  // Callers interpret 0=not initialized yet and
  // -1=too many args to fix, must parse the slow way.
  // The real initial value is special to account for nonatomicity of 64 bit
  // loads and stores.  This value may updated and read without a lock by
  // multiple threads, so is volatile.
  volatile uint64_t _fingerprint;

  // If you add a new field that points to any metaspace object, you
  // must add this field to ConstMethod::metaspace_pointers_do().

  ConstantPool*     _constants;                  // Constant pool

  // Raw stackmap data for the method
  Array<u1>*        _stackmap_data;

  int               _constMethod_size;
  ConstMethodFlags  _flags;                       // for sizing
  u1                _result_type;                 // BasicType of result

  // Size of Java bytecodes allocated immediately after Method*.
  u2                _code_size;
  u2                _name_index;                 // Method name (index in constant pool)
  u2                _signature_index;            // Method signature (index in constant pool)
  u2                _method_idnum;               // unique identification number for the method within the class
                                                 // initially corresponds to the index into the methods array.
                                                 // but this may change with redefinition
  u2                _max_stack;                  // Maximum number of entries on the expression stack
  u2                _max_locals;                 // Number of local variables used by this method
  u2                _size_of_parameters;         // size of the parameter block (receiver + arguments) in words
  u2                _num_stack_arg_slots;        // Number of arguments passed on the stack even when compiled
  u2                _orig_method_idnum;          // Original unique identification number for the method

};
```


通过_constants和_method_idnum这两个参数可以找到对应的Method实例，因为Method有ConstMethod指针，但ConstMethod没有Method指针，需要通过以下步骤查找：
ConstantPool → InstanceKlass → Method数组，通过_method_idnum获取对应的Method实例的指针


ClassFileParser::parse_method()函数解析完方法的各个属性后，接着会创建Method与ConstMethod实例保存这些属性信息”

InlineTableSizes类中定义了保存方法中相关属性的字段”


```cpp

#define INLINE_TABLES_DO(do_element)            \
  do_element(localvariable_table_length)        \
  do_element(compressed_linenumber_size)        \
  do_element(exception_table_length)            \
  do_element(checked_exceptions_length)         \
  do_element(method_parameters_length)          \
  do_element(generic_signature_index)           \
  do_element(method_annotations_length)         \
  do_element(parameter_annotations_length)      \
  do_element(type_annotations_length)           \
  do_element(default_annotations_length)

#define INLINE_TABLE_DECLARE(sym)    int _##sym;
#define INLINE_TABLE_PARAM(sym)      int sym,
#define INLINE_TABLE_INIT(sym)       _##sym(sym),
#define INLINE_TABLE_NULL(sym)       _##sym(0),
#define INLINE_TABLE_ACCESSOR(sym)   int sym() const { return _##sym; }


class InlineTableSizes : StackObj {
  // declarations
  INLINE_TABLES_DO(INLINE_TABLE_DECLARE)
  int _end;
 public:
  InlineTableSizes(
      INLINE_TABLES_DO(INLINE_TABLE_PARAM)
      int end) :
      INLINE_TABLES_DO(INLINE_TABLE_INIT)
      _end(end) {}

  // Default constructor for no inlined tables
  InlineTableSizes() :
      INLINE_TABLES_DO(INLINE_TABLE_NULL)
      _end(0) {}

  // Accessors
  INLINE_TABLES_DO(INLINE_TABLE_ACCESSOR)
};
```

在创建ConstMethod实例时，上面的一些属性值会保存到ConstMethod实例中，因此需要开辟相应的存储空间”


在Method::allocate()函数中调用ConstMethod::allocate()函数”


klassVtable与klassItable类用来实现Java方法的多态，也可以称为动态绑定，是指在应用执行期间通过判断接收对象的实际类型，然后调用对应的方法。C++为了实现多态，在对象中嵌入了虚函数表vtable，通过虚函数表来实现运行期的方法分派，Java也通过类似的虚函数表实现Java方法的动态分发”

C++中的vtable只包含虚函数，非虚函数在编译期就已经解析出正确的方法调用了。Java的vtable除了虚方法之外还包含其他的非虚方法。
访问vtable需要通过klassVtable类”

vtable表示由一组变长（前面会有一个字段描述该表的长度）连续的vtableEntry元素构成的数组。其中，每个vtableEntry封装了一个Method实例”




方法链接需要用到的数据
- _i2i_entry：定点解释器入口。方法调用会通过它进入解释器的世界，该字段一经设置后面不再改变。通过它一定能进入解释器。
-  _from_interpreter_entry：解释器入口。最开始与_i2i_entry指向同一个地方，在字节码经过JIT编译成机器代码后会改变，指向i2c适配器入口。
- _from_compiled_entry：编译器入口。最开始指向c2i适配器入口，在字节码经过编译后会改变地址，指向编译好的代码
- _code：代码入口。当编译器完成编译后会指向编译后的本地代码

链接阶段会将i2i_entry和_from_interpreter_entry都指向解释器入口，另外还会生成c2i适配器，将_from_compiled_entry也适配到解释器

各种入口的地址不会是一成不变的，当编译/解释模式切换时，入口地址也会相应切换，如从解释器切换到编译器，编译完成后会设置新的_code、_from_compiled_entry和_from_interpreter_entry入口；如果发生退优化（Deoptimization），从编译模式回退到解释模式，又会重置这些入口


## Method Handle

## VarHandles

[JEP 193: Variable Handles](https://openjdk.java.net/jeps/193)
[JEP 370: Foreign-Memory Access API (Incubator)](https://openjdk.java.net/jeps/370)

#### link_method

Called when the method_holder is getting linked.
Setup entrypoints so the method is ready to be called from interpreter, compiler, and vtables.

```cpp
void Method::link_method(const methodHandle& h_method, TRAPS) {
  // If the code cache is full, we may reenter this function for the
  // leftover methods that weren't linked.
  if (adapter() != NULL) {
    return;
  }
  assert( _code == NULL, "nothing compiled yet" );

  // Setup interpreter entrypoint
  assert(this == h_method(), "wrong h_method()" );

  assert(adapter() == NULL, "init'd to NULL");
  address entry = Interpreter::entry_for_method(h_method);
  assert(entry != NULL, "interpreter entry must be non-null");
  // Sets both _i2i_entry and _from_interpreted_entry
  set_interpreter_entry(entry);

  // Don't overwrite already registered native entries.
  if (is_native() && !has_native_function()) {
    set_native_function(
      SharedRuntime::native_method_throw_unsatisfied_link_error_entry(),
      !native_bind_event_is_interesting);
  }

  // Setup compiler entrypoint.  This is made eagerly, so we do not need
  // special handling of vtables.  An alternative is to make adapters more
  // lazily by calling make_adapter() from from_compiled_entry() for the
  // normal calls.  For vtable calls life gets more complicated.  When a
  // call-site goes mega-morphic we need adapters in all methods which can be
  // called from the vtable.  We need adapters on such methods that get loaded
  // later.  Ditto for mega-morphic itable calls.  If this proves to be a
  // problem we'll make these lazily later.
  (void) make_adapters(h_method, CHECK);

  // ONLY USE the h_method now as make_adapter may have blocked

  if (h_method->is_continuation_native_intrinsic()) {
    // the entry points to this method will be set in set_code, called when first resolving this method
    _from_interpreted_entry = NULL;
    _from_compiled_entry = NULL;
    _i2i_entry = NULL;
  }
}
```

entry_for_method

```c
static MethodKind method_kind(const methodHandle& m);
static address    entry_for_kind(MethodKind k)                { assert(0 <= k && k < number_of_method_entries, "illegal kind"); return _entry_table[k]; }
static address    entry_for_method(const methodHandle& m)     { return entry_for_kind(method_kind(m)); }
```
Java方法的类型MethodKind

```c
 enum MethodKind {
    zerolocals,                                                 // method needs locals initialization
    zerolocals_synchronized,                                    // method needs locals initialization & is synchronized
    native,                                                     // native method
    native_synchronized,                                        // native method & is synchronized
    empty,                                                      // empty method (code: _return)
    getter,                                                     // getter method
    setter,                                                     // setter method
    abstract,                                                   // abstract method (throws an AbstractMethodException)

    // ...
    invalid = -1
  };
```



#### set_code

Install compiled code.  Instantly it can execute.

```cpp

void Method::set_code(const methodHandle& mh, CompiledMethod *code) {
  assert_lock_strong(CompiledMethod_lock);
  assert( code, "use clear_code to remove code" );
  assert( mh->check_code(), "" );

  guarantee(mh->adapter() != NULL, "Adapter blob must already exist!");

  // These writes must happen in this order, because the interpreter will
  // directly jump to from_interpreted_entry which jumps to an i2c adapter
  // which jumps to _from_compiled_entry.
  mh->_code = code;             // Assign before allowing compiled code to exec

  int comp_level = code->comp_level();
  // In theory there could be a race here. In practice it is unlikely
  // and not worth worrying about.
  if (comp_level > mh->highest_comp_level()) {
    mh->set_highest_comp_level(comp_level);
  }

  OrderAccess::storestore();
  mh->_from_compiled_entry = code->verified_entry_point();
  OrderAccess::storestore();
  // Instantly compiled code can execute.
  if (!mh->is_method_handle_intrinsic())
    mh->_from_interpreted_entry = mh->get_i2c_entry();
}
```

#### clear_code

Revert to using the interpreter and clear out the nmethod

```cpp

void Method::clear_code() {
  // this may be NULL if c2i adapters have not been made yet
  // Only should happen at allocate time.
  if (adapter() == NULL) {
    _from_compiled_entry    = NULL;
  } else {
    _from_compiled_entry    = adapter()->get_c2i_entry();
  }
  OrderAccess::storestore();
  _from_interpreted_entry = _i2i_entry;
  OrderAccess::storestore();
  _code = NULL;
}
```

## Adapter

Calling Convention

- i2c
- c2i

#### gen_i2c_adapter

```cpp

void SharedRuntime::gen_i2c_adapter(MacroAssembler *masm,
                                    int total_args_passed,
                                    int comp_args_on_stack,
                                    const BasicType *sig_bt,
                                    const VMRegPair *regs) {

  // Note: r13 contains the senderSP on entry. We must preserve it since
  // we may do a i2c -> c2i transition if we lose a race where compiled
  // code goes non-entrant while we get args ready.
  // In addition we use r13 to locate all the interpreter args as
  // we must align the stack to 16 bytes on an i2c entry else we
  // lose alignment we expect in all compiled code and register
  // save code can segv when fxsave instructions find improperly
  // aligned stack pointer.

  // Adapters can be frameless because they do not require the caller
  // to perform additional cleanup work, such as correcting the stack pointer.
  // An i2c adapter is frameless because the *caller* frame, which is interpreted,
  // routinely repairs its own stack pointer (from interpreter_frame_last_sp),
  // even if a callee has modified the stack pointer.
  // A c2i adapter is frameless because the *callee* frame, which is interpreted,
  // routinely repairs its caller's stack pointer (from sender_sp, which is set
  // up via the senderSP register).
  // In other words, if *either* the caller or callee is interpreted, we can
  // get the stack pointer repaired after a call.
  // This is why c2i and i2c adapters cannot be indefinitely composed.
  // In particular, if a c2i adapter were to somehow call an i2c adapter,
  // both caller and callee would be compiled methods, and neither would
  // clean up the stack pointer changes performed by the two adapters.
  // If this happens, control eventually transfers back to the compiled
  // caller, but with an uncorrected stack, causing delayed havoc.

  if (VerifyAdapterCalls &&
      (Interpreter::code() != NULL || StubRoutines::code1() != NULL)) {
    // So, let's test for cascading c2i/i2c adapters right now.
    //  assert(Interpreter::contains($return_addr) ||
    //         StubRoutines::contains($return_addr),
    //         "i2c adapter must return to an interpreter frame");
    __ block_comment("verify_i2c { ");
    // Pick up the return address
    __ movptr(rax, Address(rsp, 0));
    Label L_ok;
    if (Interpreter::code() != NULL)
      range_check(masm, rax, r11,
                  Interpreter::code()->code_start(), Interpreter::code()->code_end(),
                  L_ok);
    if (StubRoutines::code1() != NULL)
      range_check(masm, rax, r11,
                  StubRoutines::code1()->code_begin(), StubRoutines::code1()->code_end(),
                  L_ok);
    if (StubRoutines::code2() != NULL)
      range_check(masm, rax, r11,
                  StubRoutines::code2()->code_begin(), StubRoutines::code2()->code_end(),
                  L_ok);
    const char* msg = "i2c adapter must return to an interpreter frame";
    __ block_comment(msg);
    __ stop(msg);
    __ bind(L_ok);
    __ block_comment("} verify_i2ce ");
  }

  // Must preserve original SP for loading incoming arguments because
  // we need to align the outgoing SP for compiled code.
  __ movptr(r11, rsp);

  // Pick up the return address
  __ pop(rax);

  // Convert 4-byte c2 stack slots to words.
  int comp_words_on_stack = align_up(comp_args_on_stack*VMRegImpl::stack_slot_size, wordSize)>>LogBytesPerWord;

  if (comp_args_on_stack) {
    __ subptr(rsp, comp_words_on_stack * wordSize);
  }

  // Ensure compiled code always sees stack at proper alignment
  __ andptr(rsp, -16);

  // push the return address and misalign the stack that youngest frame always sees
  // as far as the placement of the call instruction
  __ push(rax);

  // Put saved SP in another register
  const Register saved_sp = rax;
  __ movptr(saved_sp, r11);

  // Will jump to the compiled code just as if compiled code was doing it.
  // Pre-load the register-jump target early, to schedule it better.
  __ movptr(r11, Address(rbx, in_bytes(Method::from_compiled_offset())));

#if INCLUDE_JVMCI
  if (EnableJVMCI) {
    // check if this call should be routed towards a specific entry point
    __ cmpptr(Address(r15_thread, in_bytes(JavaThread::jvmci_alternate_call_target_offset())), 0);
    Label no_alternative_target;
    __ jcc(Assembler::equal, no_alternative_target);
    __ movptr(r11, Address(r15_thread, in_bytes(JavaThread::jvmci_alternate_call_target_offset())));
    __ movptr(Address(r15_thread, in_bytes(JavaThread::jvmci_alternate_call_target_offset())), 0);
    __ bind(no_alternative_target);
  }
#endif // INCLUDE_JVMCI

  // Now generate the shuffle code.  Pick up all register args and move the
  // rest through the floating point stack top.
  for (int i = 0; i < total_args_passed; i++) {
    if (sig_bt[i] == T_VOID) {
      // Longs and doubles are passed in native word order, but misaligned
      // in the 32-bit build.
      assert(i > 0 && (sig_bt[i-1] == T_LONG || sig_bt[i-1] == T_DOUBLE), "missing half");
      continue;
    }

    // Pick up 0, 1 or 2 words from SP+offset.

    assert(!regs[i].second()->is_valid() || regs[i].first()->next() == regs[i].second(),
            "scrambled load targets?");
    // Load in argument order going down.
    int ld_off = (total_args_passed - i)*Interpreter::stackElementSize;
    // Point to interpreter value (vs. tag)
    int next_off = ld_off - Interpreter::stackElementSize;
    //
    //
    //
    VMReg r_1 = regs[i].first();
    VMReg r_2 = regs[i].second();
    if (!r_1->is_valid()) {
      assert(!r_2->is_valid(), "");
      continue;
    }
    if (r_1->is_stack()) {
      // Convert stack slot to an SP offset (+ wordSize to account for return address )
      int st_off = regs[i].first()->reg2stack()*VMRegImpl::stack_slot_size + wordSize;

      // We can use r13 as a temp here because compiled code doesn't need r13 as an input
      // and if we end up going thru a c2i because of a miss a reasonable value of r13
      // will be generated.
      if (!r_2->is_valid()) {
        // sign extend???
        __ movl(r13, Address(saved_sp, ld_off));
        __ movptr(Address(rsp, st_off), r13);
      } else {
        //
        // We are using two optoregs. This can be either T_OBJECT, T_ADDRESS, T_LONG, or T_DOUBLE
        // the interpreter allocates two slots but only uses one for thr T_LONG or T_DOUBLE case
        // So we must adjust where to pick up the data to match the interpreter.
        //
        // Interpreter local[n] == MSW, local[n+1] == LSW however locals
        // are accessed as negative so LSW is at LOW address

        // ld_off is MSW so get LSW
        const int offset = (sig_bt[i]==T_LONG||sig_bt[i]==T_DOUBLE)?
                           next_off : ld_off;
        __ movq(r13, Address(saved_sp, offset));
        // st_off is LSW (i.e. reg.first())
        __ movq(Address(rsp, st_off), r13);
      }
    } else if (r_1->is_Register()) {  // Register argument
      Register r = r_1->as_Register();
      assert(r != rax, "must be different");
      if (r_2->is_valid()) {
        //
        // We are using two VMRegs. This can be either T_OBJECT, T_ADDRESS, T_LONG, or T_DOUBLE
        // the interpreter allocates two slots but only uses one for thr T_LONG or T_DOUBLE case
        // So we must adjust where to pick up the data to match the interpreter.

        const int offset = (sig_bt[i]==T_LONG||sig_bt[i]==T_DOUBLE)?
                           next_off : ld_off;

        // this can be a misaligned move
        __ movq(r, Address(saved_sp, offset));
      } else {
        // sign extend and use a full word?
        __ movl(r, Address(saved_sp, ld_off));
      }
    } else {
      if (!r_2->is_valid()) {
        __ movflt(r_1->as_XMMRegister(), Address(saved_sp, ld_off));
      } else {
        __ movdbl(r_1->as_XMMRegister(), Address(saved_sp, next_off));
      }
    }
  }

  __ push_cont_fastpath(); // Set JavaThread::_cont_fastpath to the sp of the oldest interpreted frame we know about

  // 6243940 We might end up in handle_wrong_method if
  // the callee is deoptimized as we race thru here. If that
  // happens we don't want to take a safepoint because the
  // caller frame will look interpreted and arguments are now
  // "compiled" so it is much better to make this transition
  // invisible to the stack walking code. Unfortunately if
  // we try and find the callee by normal means a safepoint
  // is possible. So we stash the desired callee in the thread
  // and the vm will find there should this case occur.

  __ movptr(Address(r15_thread, JavaThread::callee_target_offset()), rbx);

  // put Method* where a c2i would expect should we end up there
  // only needed because eof c2 resolve stubs return Method* as a result in
  // rax
  __ mov(rax, rbx);
  __ jmp(r11);
}
```

### gen_c2i_adapter

```cpp

static void gen_c2i_adapter(MacroAssembler *masm,
                            int total_args_passed,
                            int comp_args_on_stack,
                            const BasicType *sig_bt,
                            const VMRegPair *regs,
                            Label& skip_fixup) {
  // Before we get into the guts of the C2I adapter, see if we should be here
  // at all.  We've come from compiled code and are attempting to jump to the
  // interpreter, which means the caller made a static call to get here
  // (vcalls always get a compiled target if there is one).  Check for a
  // compiled target.  If there is one, we need to patch the caller's call.
  patch_callers_callsite(masm);

  __ bind(skip_fixup);

  // Since all args are passed on the stack, total_args_passed *
  // Interpreter::stackElementSize is the space we need.

  assert(total_args_passed >= 0, "total_args_passed is %d", total_args_passed);

  int extraspace = (total_args_passed * Interpreter::stackElementSize);

  // stack is aligned, keep it that way
  // This is not currently needed or enforced by the interpreter, but
  // we might as well conform to the ABI.
  extraspace = align_up(extraspace, 2*wordSize);

  // set senderSP value
  __ lea(r13, Address(rsp, wordSize));

#ifdef ASSERT
  __ check_stack_alignment(r13, "sender stack not aligned");
#endif
  if (extraspace > 0) {
    // Pop the return address
    __ pop(rax);

    __ subptr(rsp, extraspace);

    // Push the return address
    __ push(rax);

    // Account for the return address location since we store it first rather
    // than hold it in a register across all the shuffling
    extraspace += wordSize;
  }

#ifdef ASSERT
  __ check_stack_alignment(rsp, "callee stack not aligned", wordSize, rax);
#endif

  // Now write the args into the outgoing interpreter space
  for (int i = 0; i < total_args_passed; i++) {
    if (sig_bt[i] == T_VOID) {
      assert(i > 0 && (sig_bt[i-1] == T_LONG || sig_bt[i-1] == T_DOUBLE), "missing half");
      continue;
    }

    // offset to start parameters
    int st_off   = (total_args_passed - i) * Interpreter::stackElementSize;
    int next_off = st_off - Interpreter::stackElementSize;

    // Say 4 args:
    // i   st_off
    // 0   32 T_LONG
    // 1   24 T_VOID
    // 2   16 T_OBJECT
    // 3    8 T_BOOL
    // -    0 return address
    //
    // However to make thing extra confusing. Because we can fit a long/double in
    // a single slot on a 64 bt vm and it would be silly to break them up, the interpreter
    // leaves one slot empty and only stores to a single slot. In this case the
    // slot that is occupied is the T_VOID slot. See I said it was confusing.

    VMReg r_1 = regs[i].first();
    VMReg r_2 = regs[i].second();
    if (!r_1->is_valid()) {
      assert(!r_2->is_valid(), "");
      continue;
    }
    if (r_1->is_stack()) {
      // memory to memory use rax
      int ld_off = r_1->reg2stack() * VMRegImpl::stack_slot_size + extraspace;
      if (!r_2->is_valid()) {
        // sign extend??
        __ movl(rax, Address(rsp, ld_off));
        __ movptr(Address(rsp, st_off), rax);

      } else {

        __ movq(rax, Address(rsp, ld_off));

        // Two VMREgs|OptoRegs can be T_OBJECT, T_ADDRESS, T_DOUBLE, T_LONG
        // T_DOUBLE and T_LONG use two slots in the interpreter
        if ( sig_bt[i] == T_LONG || sig_bt[i] == T_DOUBLE) {
          // ld_off == LSW, ld_off+wordSize == MSW
          // st_off == MSW, next_off == LSW
          __ movq(Address(rsp, next_off), rax);
#ifdef ASSERT
          // Overwrite the unused slot with known junk
          __ mov64(rax, CONST64(0xdeadffffdeadaaaa));
          __ movptr(Address(rsp, st_off), rax);
#endif /* ASSERT */
        } else {
          __ movq(Address(rsp, st_off), rax);
        }
      }
    } else if (r_1->is_Register()) {
      Register r = r_1->as_Register();
      if (!r_2->is_valid()) {
        // must be only an int (or less ) so move only 32bits to slot
        // why not sign extend??
        __ movl(Address(rsp, st_off), r);
      } else {
        // Two VMREgs|OptoRegs can be T_OBJECT, T_ADDRESS, T_DOUBLE, T_LONG
        // T_DOUBLE and T_LONG use two slots in the interpreter
        if ( sig_bt[i] == T_LONG || sig_bt[i] == T_DOUBLE) {
          // long/double in gpr
#ifdef ASSERT
          // Overwrite the unused slot with known junk
          __ mov64(rax, CONST64(0xdeadffffdeadaaab));
          __ movptr(Address(rsp, st_off), rax);
#endif /* ASSERT */
          __ movq(Address(rsp, next_off), r);
        } else {
          __ movptr(Address(rsp, st_off), r);
        }
      }
    } else {
      assert(r_1->is_XMMRegister(), "");
      if (!r_2->is_valid()) {
        // only a float use just part of the slot
        __ movflt(Address(rsp, st_off), r_1->as_XMMRegister());
      } else {
#ifdef ASSERT
        // Overwrite the unused slot with known junk
        __ mov64(rax, CONST64(0xdeadffffdeadaaac));
        __ movptr(Address(rsp, st_off), rax);
#endif /* ASSERT */
        __ movdbl(Address(rsp, next_off), r_1->as_XMMRegister());
      }
    }
  }

  // Schedule the branch target address early.
  __ movptr(rcx, Address(rbx, in_bytes(Method::interpreter_entry_offset())));
  __ jmp(rcx);
}
```


## vtable


klassVtable与klassItable类用来实现Java方法的多态，也可以称为动态绑定，是指在应用执行期间通过判断接收对象的实际类型，然后调用对应的方法。C++为了实现多态，在对象中嵌入了虚函数表vtable，通过虚函数表来实现运行期的方法分派，Java也通过类似的虚函数表实现Java方法的动态分发”

C++中的vtable只包含虚函数，非虚函数在编译期就已经解析出正确的方法调用了。Java的vtable除了虚方法之外还包含其他的非虚方法。
访问vtable需要通过klassVtable类”

vtable表示由一组变长（前面会有一个字段描述该表的长度）连续的vtableEntry元素构成的数组。其中，每个vtableEntry封装了一个Method实例”

```c
class klassVtable {
  Klass*       _klass;            // my klass
  int          _tableOffset;      // offset of start of vtable data within klass
  int          _length;           // length of vtable (number of entries)
#ifndef PRODUCT
  int          _verify_count;     // to make verify faster
#endif
};
```

vtable中的一条记录用vtableEntry表示 vtableEntry类只定义了一个_method属性，只是对Method*做了简单包装

```cpp
class vtableEntry {
  friend class VMStructs;
  friend class JVMCIVMStructs;

 public:
  // size in words
  static int size()          { return sizeof(vtableEntry) / wordSize; }
  static int size_in_bytes() { return sizeof(vtableEntry); }

  static ByteSize method_offset() { return byte_offset_of(vtableEntry, _method); }
  Method* method() const    { return _method; }
  Method** method_addr()    { return &_method; }

 private:
  Method* _method;
  void set(Method* method)  { assert(method != nullptr, "use clear"); _method = method; }
  void clear()                { _method = nullptr; }
  void print()                                        PRODUCT_RETURN;
  void verify(klassVtable* vt, outputStream* st);

  friend class klassVtable;
};
```


可以开启VM参数`-Xlog:vtables=trace`查看所有类的虚表的创建过程(非production)
在调用虚方法时虚拟机会在运行时常量池中查找n的静态类型Node的print方法，获取它在Node虚表中的index，接着用index定位动态类型AddNode虚表中的虚方法进行调用

> [!TIP]
>
> gcc使用-fdump-class-hierarchy输出虚表，clang使用-Xclang -fdump-vtable-layouts输出虚表，msvc使用/d1reportAllClassLayout输出虚表


update_inherited_vtable



### initialize_vtable

called when [Linking Class](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=Linking)

Revised lookup semantics   introduced 1.3 (Kestrel beta)

```cpp
// share/oops/klassVtable.cpp
// Revised lookup semantics   introduced 1.3 (Kestrel beta)
void klassVtable::initialize_vtable(GrowableArray<InstanceKlass*>* supers) {

  // Note:  Arrays can have intermediate array supers.  Use java_super to skip them.
  InstanceKlass* super = _klass->java_super();

  bool is_shared = _klass->is_shared();
  Thread* current = Thread::current();

  if (!_klass->is_array_klass()) {
    ResourceMark rm(current);
    log_develop_debug(vtables)("Initializing: %s", _klass->name()->as_C_string());
  }

  if (Universe::is_bootstrapping()) {
    assert(!is_shared, "sanity");
    // just clear everything
    for (int i = 0; i < _length; i++) table()[i].clear();
    return;
  }

  int super_vtable_len = initialize_from_super(super);
  if (_klass->is_array_klass()) {
    assert(super_vtable_len == _length, "arrays shouldn't introduce new methods");
  } else {
    assert(_klass->is_instance_klass(), "must be InstanceKlass");

    Array<Method*>* methods = ik()->methods();
    int len = methods->length();
    int initialized = super_vtable_len;

    // Check each of this class's methods against super;
    // if override, replace in copy of super vtable, otherwise append to end
    for (int i = 0; i < len; i++) {
      // update_inherited_vtable can stop for gc - ensure using handles
      methodHandle mh(current, methods->at(i));

      bool needs_new_entry = update_inherited_vtable(current, mh, super_vtable_len, -1, supers);

      if (needs_new_entry) {
        put_method_at(mh(), initialized);
        mh->set_vtable_index(initialized); // set primary vtable index
        initialized++;
      }
    }

    // update vtable with default_methods
    Array<Method*>* default_methods = ik()->default_methods();
    if (default_methods != nullptr) {
      len = default_methods->length();
      if (len > 0) {
        Array<int>* def_vtable_indices = ik()->default_vtable_indices();
        assert(def_vtable_indices != nullptr, "should be created");
        assert(def_vtable_indices->length() == len, "reinit vtable len?");
        for (int i = 0; i < len; i++) {
          bool needs_new_entry;
          {
            // Reduce the scope of this handle so that it is fetched again.
            // The methodHandle keeps it from being deleted by RedefineClasses while
            // we're using it.
            methodHandle mh(current, default_methods->at(i));
            assert(!mh->is_private(), "private interface method in the default method list");
            needs_new_entry = update_inherited_vtable(current, mh, super_vtable_len, i, supers);
          }

          // needs new entry
          if (needs_new_entry) {
            // Refetch this default method in case of redefinition that might
            // happen during constraint checking in the update_inherited_vtable call above.
            Method* method = default_methods->at(i);
            put_method_at(method, initialized);
            if (is_preinitialized_vtable()) {
              // At runtime initialize_vtable is rerun for a shared class
              // (loaded by the non-boot loader) as part of link_class_impl().
              // The dumptime vtable index should be the same as the runtime index.
              assert(def_vtable_indices->at(i) == initialized,
                     "dump time vtable index is different from runtime index");
            } else {
              def_vtable_indices->at_put(i, initialized); //set vtable index
            }
            initialized++;
          }
        }
      }
    }

    // add miranda methods; it will also return the updated initialized
    // Interfaces do not need interface methods in their vtables
    // This includes miranda methods and during later processing, default methods
    if (!ik()->is_interface()) {
      initialized = fill_in_mirandas(current, initialized);
    }

    // In class hierarchies where the accessibility is not increasing (i.e., going from private ->
    // package_private -> public/protected), the vtable might actually be smaller than our initial
    // calculation, for classfile versions for which we do not do transitive override
    // calculations.
    if (ik()->major_version() >= VTABLE_TRANSITIVE_OVERRIDE_VERSION) {
      assert(initialized == _length, "vtable initialization failed");
    } else {
      assert(initialized <= _length, "vtable initialization failed");
      for(;initialized < _length; initialized++) {
        table()[initialized].clear();
      }
    }
    NOT_PRODUCT(verify(tty, true));
  }
}
```

Update child's copy of super vtable for overrides
OR return true if a new vtable entry is required.
Only called for InstanceKlass's, i.e. not for arrays
If that changed, could not use _klass as handle for klass

update_inherited_vtable


```c
// Update child's copy of super vtable for overrides
// OR return true if a new vtable entry is required.
// Only called for InstanceKlass's, i.e. not for arrays
// If that changed, could not use _klass as handle for klass
bool klassVtable::update_inherited_vtable(Thread* current,
                                          const methodHandle& target_method,
                                          int super_vtable_len, int default_index,
                                          GrowableArray<InstanceKlass*>* supers) {
  bool allocate_new = true;

  InstanceKlass* klass = ik();

  Array<int>* def_vtable_indices = nullptr;
  bool is_default = false;

  // default methods are non-private concrete methods in superinterfaces which are added
  // to the vtable with their real method_holder.
  // Since vtable and itable indices share the same storage, don't touch
  // the default method's real vtable/itable index.
  // default_vtable_indices stores the vtable value relative to this inheritor
  if (default_index >= 0 ) {
    is_default = true;
    def_vtable_indices = klass->default_vtable_indices();
    assert(!target_method->is_private(), "private interface method flagged as default");
    assert(def_vtable_indices != nullptr, "def vtable alloc?");
    assert(default_index <= def_vtable_indices->length(), "def vtable len?");
  } else {
    assert(klass == target_method->method_holder(), "caller resp.");
    // Initialize the method's vtable index to "nonvirtual".
    // If we allocate a vtable entry, we will update it to a non-negative number.
    target_method->set_vtable_index(Method::nonvirtual_vtable_index);
  }

  // Private, static and <init> methods are never in
  if (target_method->is_private() || target_method->is_static() ||
      (target_method->name()->fast_compare(vmSymbols::object_initializer_name()) == 0)) {
    return false;
  }

  if (target_method->is_final_method(klass->access_flags())) {
    // a final method never needs a new entry; final methods can be statically
    // resolved and they have to be present in the vtable only if they override
    // a super's method, in which case they re-use its entry
    allocate_new = false;
  } else if (klass->is_interface()) {
    allocate_new = false;  // see note below in needs_new_vtable_entry
    // An interface never allocates new vtable slots, only inherits old ones.
    // This method will either be assigned its own itable index later,
    // or be assigned an inherited vtable index in the loop below.
    // default methods inherited by classes store their vtable indices
    // in the inheritor's default_vtable_indices.
    // default methods inherited by interfaces may already have a
    // valid itable index, if so, don't change it.
    // Overpass methods in an interface will be assigned an itable index later
    // by an inheriting class.
    if ((!is_default || !target_method->has_itable_index())) {
      target_method->set_vtable_index(Method::pending_itable_index);
    }
  }

  // we need a new entry if there is no superclass
  Klass* super = klass->super();
  if (super == nullptr) {
    return allocate_new;
  }

  // search through the vtable and update overridden entries
  // Since check_signature_loaders acquires SystemDictionary_lock
  // which can block for gc, once we are in this loop, use handles
  // For classfiles built with >= jdk7, we now look for transitive overrides

  Symbol* name = target_method->name();
  Symbol* signature = target_method->signature();

  Klass* target_klass = target_method->method_holder();
  assert(target_klass != nullptr, "impossible");
  if (target_klass == nullptr) {
    target_klass = _klass;
  }

  HandleMark hm(current);
  Handle target_loader(current, target_klass->class_loader());

  Symbol* target_classname = target_klass->name();
  for(int i = 0; i < super_vtable_len; i++) {
    Method* super_method;
    if (is_preinitialized_vtable()) {
      // If this is a shared class, the vtable is already in the final state (fully
      // initialized). Need to look at the super's vtable.
      klassVtable superVtable = super->vtable();
      super_method = superVtable.method_at(i);
    } else {
      super_method = method_at(i);
    }
    // Check if method name matches.  Ignore match if klass is an interface and the
    // matching method is a non-public java.lang.Object method.  (See JVMS 5.4.3.4)
    // This is safe because the method at this slot should never get invoked.
    // (TBD: put in a method to throw NoSuchMethodError if this slot is ever used.)
    if (super_method->name() == name && super_method->signature() == signature &&
        (!klass->is_interface() ||
         !SystemDictionary::is_nonpublic_Object_method(super_method))) {

      // get super_klass for method_holder for the found method
      InstanceKlass* super_klass =  super_method->method_holder();

      // Whether the method is being overridden
      bool overrides = false;

      // private methods are also never overridden
      if (!super_method->is_private() &&
          (is_default ||
           can_be_overridden(super_method, target_loader, target_classname) ||
           (klass->major_version() >= VTABLE_TRANSITIVE_OVERRIDE_VERSION &&
             (super_klass = find_transitive_override(super_klass,
                                                     target_method, i, target_loader,
                                                     target_classname)) != nullptr))) {

        // Package private methods always need a new entry to root their own
        // overriding. They may also override other methods.
        if (!target_method->is_package_private()) {
          allocate_new = false;
        }

        // Set the vtable index before the constraint check safepoint, which potentially
        // redefines this method if this method is a default method belonging to a
        // super class or interface.
        put_method_at(target_method(), i);
        // Save super for constraint checking.
        if (supers != nullptr) {
          supers->at_put(i, super_klass);
        }

        overrides = true;
        if (!is_default) {
          target_method->set_vtable_index(i);
        } else {
          if (def_vtable_indices != nullptr) {
            if (is_preinitialized_vtable()) {
              // At runtime initialize_vtable is rerun as part of link_class_impl()
              // for a shared class loaded by the non-boot loader.
              // The dumptime vtable index should be the same as the runtime index.
              assert(def_vtable_indices->at(default_index) == i,
                     "dump time vtable index is different from runtime index");
            } else {
              def_vtable_indices->at_put(default_index, i);
            }
          }
          assert(super_method->is_default_method() || super_method->is_overpass()
                 || super_method->is_abstract(), "default override error");
        }
      } else {
        overrides = false;
      }
      log_vtables(i, overrides, target_method, target_klass, super_method);
    }
  }
  return allocate_new;
}
```

## itable

```c
class klassItable {
 private:
  InstanceKlass*       _klass;             // my klass
  int                  _table_offset;      // offset of start of itable data within klass (in words)
  int                  _size_offset_table; // size of offset table (in itableOffset entries)
  int                  _size_method_table; // size of methodtable (in itableMethodEntry entries)

  //

};
```

### initialize_itable


called when [Linking Class](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=Linking)

```c
void klassItable::initialize_itable(GrowableArray<Method*>* supers) {
  if (_klass->is_interface()) {
    // This needs to go after vtable indices are assigned but
    // before implementors need to know the number of itable indices.
    assign_itable_indices_for_interface(InstanceKlass::cast(_klass));
  }

  // Cannot be setup doing bootstrapping, interfaces don't have
  // itables, and klass with only ones entry have empty itables
  if (Universe::is_bootstrapping() ||
      _klass->is_interface() ||
      _klass->itable_length() == itableOffsetEntry::size()) return;

  // There's always an extra itable entry so we can null-terminate it.
  guarantee(size_offset_table() >= 1, "too small");
  int num_interfaces = size_offset_table() - 1;
  if (num_interfaces > 0) {
    if (log_develop_is_enabled(Debug, itables)) {
      ResourceMark rm;
      log_develop_debug(itables)("%3d: Initializing itables for %s", ++initialize_count,
                       _klass->name()->as_C_string());
    }

    // Iterate through all interfaces
    for(int i = 0; i < num_interfaces; i++) {
      itableOffsetEntry* ioe = offset_entry(i);
      InstanceKlass* interf = ioe->interface_klass();
      assert(interf != nullptr && ioe->offset() != 0, "bad offset entry in itable");
      initialize_itable_for_interface(ioe->offset(), interf, supers,
                       (ioe->offset() - offset_entry(0)->offset())/wordSize);
    }
  }
  // Check that the last entry is empty
  itableOffsetEntry* ioe = offset_entry(size_offset_table() - 1);
  guarantee(ioe->interface_klass() == nullptr && ioe->offset() == 0, "terminator entry missing");
}
```


```c
void klassItable::initialize_itable_for_interface(int method_table_offset, InstanceKlass* interf,
                                                  GrowableArray<Method*>* supers,
                                                  int start_offset) {
  assert(interf->is_interface(), "must be");
  Array<Method*>* methods = interf->methods();
  int nof_methods = methods->length();

  int ime_count = method_count_for_interface(interf);
  for (int i = 0; i < nof_methods; i++) {
    Method* m = methods->at(i);
    Method* target = nullptr;
    if (m->has_itable_index()) {
      // This search must match the runtime resolution, i.e. selection search for invokeinterface
      // to correctly enforce loader constraints for interface method inheritance.
      // Private methods are skipped as a private class method can never be the implementation
      // of an interface method.
      // Invokespecial does not perform selection based on the receiver, so it does not use
      // the cached itable.
      target = LinkResolver::lookup_instance_method_in_klasses(_klass, m->name(), m->signature(),
                                                               Klass::PrivateLookupMode::skip);
    }
    if (target == nullptr || !target->is_public() || target->is_abstract() || target->is_overpass()) {
      assert(target == nullptr || !target->is_overpass() || target->is_public(),
             "Non-public overpass method!");
      // Entry does not resolve. Leave it empty for AbstractMethodError or other error.
      if (!(target == nullptr) && !target->is_public()) {
        // Stuff an IllegalAccessError throwing method in there instead.
        itableOffsetEntry::method_entry(_klass, method_table_offset)[m->itable_index()].
            initialize(_klass, Universe::throw_illegal_access_error());
      }
    } else {

      int ime_num = m->itable_index();
      assert(ime_num < ime_count, "oob");

      // Save super interface method to perform constraint checks.
      // The method is in the error message, that's why.
      if (supers != nullptr) {
        supers->at_put(start_offset + ime_num, m);
      }

      itableOffsetEntry::method_entry(_klass, method_table_offset)[ime_num].initialize(_klass, target);
      if (log_develop_is_enabled(Trace, itables)) {
        ResourceMark rm;
        if (target != nullptr) {
          LogTarget(Trace, itables) lt;
          LogStream ls(lt);
          char* sig = target->name_and_sig_as_C_string();
          ls.print("interface: %s, ime_num: %d, target: %s, method_holder: %s ",
                       interf->internal_name(), ime_num, sig,
                       target->method_holder()->internal_name());
          ls.print("target_method flags: ");
          target->print_linkage_flags(&ls);
          ls.cr();
        }
      }
    }
  }
}
```



## Link

hotspot/share/interpreter/linkResolver.hpp

All the necessary definitions for run-time link resolution.
CallInfo provides all the information gathered for a particular linked call site after resolving it. A link is any reference made from within the bytecodes of a method to an object outside of that method. If the info is invalid, the link has not been resolved successfully.

The LinkResolver is used to resolve constant-pool references at run-time.
It does all necessary link-time checks & throws exceptions if necessary.


Link information for getfield/putfield & getstatic/putstatic bytecodes is represented using a fieldDescriptor.

```cpp
class LinkInfo : public StackObj {
  Symbol*     _name;            // extracted from JVM_CONSTANT_NameAndType
  Symbol*     _signature;
  Klass*      _resolved_klass;  // class that the constant pool entry points to
  Klass*      _current_klass;   // class that owns the constant pool
  methodHandle _current_method;  // sending method
  bool        _check_access;
  bool        _check_loader_constraints;
  constantTag _tag;

 public:
  enum class AccessCheck { required, skip };
  enum class LoaderConstraintCheck { required, skip };

  LinkInfo(const constantPoolHandle& pool, int index, const methodHandle& current_method, Bytecodes::Code code, TRAPS);
  LinkInfo(const constantPoolHandle& pool, int index, Bytecodes::Code code, TRAPS);

  // Condensed information from other call sites within the vm.
  LinkInfo(Klass* resolved_klass, Symbol* name, Symbol* signature, Klass* current_klass,
           AccessCheck check_access = AccessCheck::required,
           LoaderConstraintCheck check_loader_constraints = LoaderConstraintCheck::required,
           constantTag tag = JVM_CONSTANT_Invalid) :
      _name(name),
      _signature(signature),
      _resolved_klass(resolved_klass),
      _current_klass(current_klass),
      _current_method(methodHandle()),
      _check_access(check_access == AccessCheck::required),
      _check_loader_constraints(check_loader_constraints == LoaderConstraintCheck::required),
      _tag(tag) {
    assert(_resolved_klass != nullptr, "must always have a resolved_klass");
  }

  LinkInfo(Klass* resolved_klass, Symbol* name, Symbol* signature, const methodHandle& current_method,
           AccessCheck check_access = AccessCheck::required,
           LoaderConstraintCheck check_loader_constraints = LoaderConstraintCheck::required,
           constantTag tag = JVM_CONSTANT_Invalid) :
    LinkInfo(resolved_klass, name, signature, current_method->method_holder(), check_access, check_loader_constraints, tag) {
    _current_method = current_method;
  }

  // Case where we just find the method and don't check access against the current class, used by JavaCalls
  LinkInfo(Klass* resolved_klass, Symbol*name, Symbol* signature) :
    LinkInfo(resolved_klass, name, signature, nullptr, AccessCheck::skip, LoaderConstraintCheck::skip,
             JVM_CONSTANT_Invalid) {}

  // accessors
  Symbol* name() const                  { return _name; }
  Symbol* signature() const             { return _signature; }
  Klass* resolved_klass() const         { return _resolved_klass; }
  Klass* current_klass() const          { return _current_klass; }
  Method* current_method() const        { return _current_method(); }
  constantTag tag() const               { return _tag; }
  bool check_access() const             { return _check_access; }
  bool check_loader_constraints() const { return _check_loader_constraints; }
  void         print()  PRODUCT_RETURN;
};
```


```cpp
class LinkResolver: AllStatic {
  friend class klassVtable;
  friend class klassItable;

 private:

  static Method* lookup_method_in_klasses(const LinkInfo& link_info,
                                          bool checkpolymorphism,
                                          bool in_imethod_resolve);
  static Method* lookup_method_in_interfaces(const LinkInfo& link_info);

  static Method* lookup_polymorphic_method(const LinkInfo& link_info,
                                           Handle *appendix_result_or_null, TRAPS);
 JVMCI_ONLY(public:) // Needed for CompilerToVM.resolveMethod()
  // Not Linktime so doesn't take LinkInfo
  static Method* lookup_instance_method_in_klasses (Klass* klass, Symbol* name, Symbol* signature,
                                                    Klass::PrivateLookupMode private_mode);
 JVMCI_ONLY(private:)

  // Similar loader constraint checking functions that throw
  // LinkageError with descriptive message.
  static void check_method_loader_constraints(const LinkInfo& link_info,
                                              const methodHandle& resolved_method,
                                              const char* method_type, TRAPS);
  static void check_field_loader_constraints(Symbol* field, Symbol* sig,
                                             Klass* current_klass,
                                             Klass* sel_klass, TRAPS);

  static Method* resolve_interface_method(const LinkInfo& link_info, Bytecodes::Code code, TRAPS);
  static Method* resolve_method          (const LinkInfo& link_info, Bytecodes::Code code, TRAPS);

  static Method* linktime_resolve_static_method    (const LinkInfo& link_info, TRAPS);
  static Method* linktime_resolve_special_method   (const LinkInfo& link_info, TRAPS);
  static Method* linktime_resolve_virtual_method   (const LinkInfo& link_info, TRAPS);
  static Method* linktime_resolve_interface_method (const LinkInfo& link_info, TRAPS);

  static void runtime_resolve_special_method    (CallInfo& result,
                                                 const LinkInfo& link_info,
                                                 const methodHandle& resolved_method,
                                                 Handle recv, TRAPS);

  static void runtime_resolve_virtual_method    (CallInfo& result,
                                                 const methodHandle& resolved_method,
                                                 Klass* resolved_klass,
                                                 Handle recv,
                                                 Klass* recv_klass,
                                                 bool check_null_and_abstract, TRAPS);
  static void runtime_resolve_interface_method  (CallInfo& result,
                                                 const methodHandle& resolved_method,
                                                 Klass* resolved_klass,
                                                 Handle recv,
                                                 Klass* recv_klass,
                                                 bool check_null_and_abstract, TRAPS);

  static bool resolve_previously_linked_invokehandle(CallInfo& result,
                                                     const LinkInfo& link_info,
                                                     const constantPoolHandle& pool,
                                                     int index, TRAPS);

  static void check_field_accessability(Klass* ref_klass,
                                        Klass* resolved_klass,
                                        Klass* sel_klass,
                                        const fieldDescriptor& fd, TRAPS);
  static void check_method_accessability(Klass* ref_klass,
                                         Klass* resolved_klass,
                                         Klass* sel_klass,
                                         const methodHandle& sel_method, TRAPS);

  // runtime resolving from constant pool
  static void resolve_invokestatic   (CallInfo& result,
                                      const constantPoolHandle& pool, int index, TRAPS);
  static void resolve_invokespecial  (CallInfo& result, Handle recv,
                                      const constantPoolHandle& pool, int index, TRAPS);
  static void resolve_invokevirtual  (CallInfo& result, Handle recv,
                                      const constantPoolHandle& pool, int index, TRAPS);
  static void resolve_invokeinterface(CallInfo& result, Handle recv,
                                      const constantPoolHandle& pool, int index, TRAPS);
  static void resolve_invokedynamic  (CallInfo& result,
                                      const constantPoolHandle& pool, int index, TRAPS);
  static void resolve_invokehandle   (CallInfo& result,
                                      const constantPoolHandle& pool, int index, TRAPS);
 public:
  // constant pool resolving
  static void check_klass_accessibility(Klass* ref_klass, Klass* sel_klass, TRAPS);

  // static resolving calls (will not run any Java code);
  // used only from Bytecode_invoke::static_target
  static Method* resolve_method_statically(Bytecodes::Code code,
                                           const constantPoolHandle& pool,
                                           int index, TRAPS);

  static void resolve_continuation_enter(CallInfo& callinfo, TRAPS);

  static void resolve_field_access(fieldDescriptor& result,
                                   const constantPoolHandle& pool,
                                   int index,
                                   const methodHandle& method,
                                   Bytecodes::Code byte, TRAPS);
  static void resolve_field(fieldDescriptor& result, const LinkInfo& link_info,
                            Bytecodes::Code access_kind,
                            bool initialize_class, TRAPS);

  static void resolve_static_call   (CallInfo& result,
                                     const LinkInfo& link_info,
                                     bool initialize_klass, TRAPS);
  static void resolve_special_call  (CallInfo& result,
                                     Handle recv,
                                     const LinkInfo& link_info,
                                     TRAPS);
  static void resolve_virtual_call  (CallInfo& result, Handle recv, Klass* recv_klass,
                                     const LinkInfo& link_info,
                                     bool check_null_and_abstract, TRAPS);
  static void resolve_interface_call(CallInfo& result, Handle recv, Klass* recv_klass,
                                     const LinkInfo& link_info,
                                     bool check_null_and_abstract, TRAPS);
  static void resolve_handle_call   (CallInfo& result,
                                     const LinkInfo& link_info, TRAPS);
  static void resolve_dynamic_call  (CallInfo& result,
                                     BootstrapInfo& bootstrap_specifier, TRAPS);

  // same as above for compile-time resolution; but returns null handle instead of throwing
  // an exception on error also, does not initialize klass (i.e., no side effects)
  static Method* resolve_virtual_call_or_null(Klass* receiver_klass,
                                              const LinkInfo& link_info);
  static Method* resolve_interface_call_or_null(Klass* receiver_klass,
                                                const LinkInfo& link_info);
  static Method* resolve_static_call_or_null(const LinkInfo& link_info);
  static Method* resolve_special_call_or_null(const LinkInfo& link_info);

  static int vtable_index_of_interface_method(Klass* klass, const methodHandle& resolved_method);

  // same as above for compile-time resolution; returns vtable_index if current_klass if linked
  static int resolve_virtual_vtable_index  (Klass* receiver_klass,
                                            const LinkInfo& link_info);

  // static resolving for compiler (does not throw exceptions, returns null handle if unsuccessful)
  static Method* linktime_resolve_virtual_method_or_null  (const LinkInfo& link_info);
  static Method* linktime_resolve_interface_method_or_null(const LinkInfo& link_info);

  // runtime resolving from constant pool
  static void resolve_invoke(CallInfo& result, Handle recv,
                             const constantPoolHandle& pool, int index,
                             Bytecodes::Code byte, TRAPS);

  // runtime resolving from attached method
  static void resolve_invoke(CallInfo& result, Handle& recv,
                             const methodHandle& attached_method,
                             Bytecodes::Code byte, TRAPS);

  // Only resolved method known.
  static void throw_abstract_method_error(const methodHandle& resolved_method, TRAPS) {
    throw_abstract_method_error(resolved_method, methodHandle(), nullptr, CHECK);
  }
  // Resolved method and receiver klass know.
  static void throw_abstract_method_error(const methodHandle& resolved_method, Klass *recv_klass, TRAPS) {
    throw_abstract_method_error(resolved_method, methodHandle(), recv_klass, CHECK);
  }
  // Selected method is abstract.
  static void throw_abstract_method_error(const methodHandle& resolved_method,
                                          const methodHandle& selected_method,
                                          Klass *recv_klass, TRAPS);
};
```


## CDS

Class Data Sharing since JDK5

JEP310 Application Class Data Sharing

JEP350 DynamicCDS

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
