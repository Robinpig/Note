## Introduction

TemplateInterpreter

## AbstractInterpreter

The basic behavior of the JVM interpreter can be thought of as essentially “`a switch inside a while loop`” — processing each opcode of the program independently of the last,
using the evaluation stack to hold intermediate values.

This file contains the platform-independent parts of the **abstract interpreter** and the **abstract interpreter generator**.

Organization of the interpreter(s).
There exists two different interpreters in hotpot an assembly language version (aka [template interpreter](/docs/CS/Java/JDK/JVM/interpreter.md?id=TemplateInterpreter) and a high level language version(aka [c++ interpreter](/docs/CS/Java/JDK/JVM/interpreter.md?id=CppInterpreter)).

The interpreter code in [StubQueue](/docs/CS/Java/JDK/JVM/interpreter.md?id=StubQueue)

```cpp

class AbstractInterpreter: AllStatic {
 protected:
  static StubQueue* _code;                                      // the interpreter code (codelets)

  static bool       _notice_safepoints;                         // true if safepoints are activated

  static address    _native_entry_begin;                        // Region for native entry code
  static address    _native_entry_end;

  // method entry points
  static address    _entry_table[number_of_method_entries];     // entry points for a given method
  static address    _native_abi_to_tosca[number_of_result_handlers];  // for native method result handlers
  static address    _slow_signature_handler;                              // the native method generic (slow) signature handler

  static address    _rethrow_exception_entry;                   // rethrows an activation in previous frame

  friend class      AbstractInterpreterGenerator;
  friend class      InterpreterMacroAssembler;

}

```

### StubQueue

A StubQueue maintains a queue of stubs. And BufferBlob store in [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md).

StubQueue是用来保存生成的本地代码的Stub队列，队列每一个元素对应一个InterpreterCodelet对象，InterpreterCodelet对象继承自抽象基类Stub，包含了字节码对应的本地代码以及一些调试和输出信息。 



> [!NOTE]
>
> All sizes (spaces) are given in bytes.

```cpp
// share/code/stubs.hpp
class StubQueue: public CHeapObj<mtCode> {
 private:
  StubInterface* _stub_interface;                // the interface prototype
  address        _stub_buffer;                   // where all stubs are stored
  int            _buffer_size;                   // the buffer size in bytes
  int            _buffer_limit;                  // the (byte) index of the actual buffer limit (_buffer_limit <= _buffer_size)
  int            _queue_begin;                   // the (byte) index of the first queue entry (word-aligned)
  int            _queue_end;                     // the (byte) index of the first entry after the queue (word-aligned)
  int            _number_of_stubs;               // the number of buffered stubs
  Mutex* const   _mutex;                         // the lock used for a (request, commit) transaction

  void  check_index(int i) const                 { assert(0 <= i && i < _buffer_limit && i % CodeEntryAlignment == 0, "illegal index"); }
  bool  is_contiguous() const                    { return _queue_begin <= _queue_end; }
  int   index_of(Stub* s) const                  { int i = (address)s - _stub_buffer; check_index(i); return i; }
  Stub* stub_at(int i) const                     { check_index(i); return (Stub*)(_stub_buffer + i); }
  Stub* current_stub() const                     { return stub_at(_queue_end); }

  // Stub functionality accessed via interface
  void  stub_initialize(Stub* s, int size)       { assert(size % CodeEntryAlignment == 0, "size not aligned"); _stub_interface->initialize(s, size); }
  void  stub_finalize(Stub* s)                   { _stub_interface->finalize(s); }
  int   stub_size(Stub* s) const                 { return _stub_interface->size(s); }
  bool  stub_contains(Stub* s, address pc) const { return _stub_interface->code_begin(s) <= pc && pc < _stub_interface->code_end(s); }
  int   stub_code_size_to_size(int code_size) const { return _stub_interface->code_size_to_size(code_size); }
  void  stub_verify(Stub* s)                     { _stub_interface->verify(s); }
  void  stub_print(Stub* s)                      { _stub_interface->print(s); }
  
}
```

#### Implementation of StubQueue

Standard wrap-around queue implementation; the queue dimensions are specified by the _queue_begin & _queue_end indices.
The queue can be in two states (transparent to the outside):

a) contiguous state: all queue entries in one block (or empty)

```
Queue: |...|XXXXXXX|...............|
       ^0  ^begin  ^end            ^size = limit
           |_______|
           one block
```

b) non-contiguous state: queue entries in two blocks

```
Queue: |XXX|.......|XXXXXXX|.......|
       ^0  ^end    ^begin  ^limit  ^size
       |___|       |_______|
        1st block  2nd block
```

In the non-contiguous state, the wrap-around point is indicated via the _buffer_limit index since the last queue entry may not fill up the queue completely in
which case we need to know where the 2nd block's end is to do the proper wrap-around.
When removing the last entry of the 2nd block, _buffer_limit is reset to _buffer_size.

```cpp
StubQueue::StubQueue(StubInterface* stub_interface, int buffer_size,
Mutex* lock, const char* name) : _mutex(lock) {
intptr_t size = align_up(buffer_size, 2*BytesPerWord);
BufferBlob* blob = BufferBlob::create(name, size);
if( blob == NULL) {
vm_exit_out_of_memory(size, OOM_MALLOC_ERROR, "CodeCache: no room for %s", name);
}
_stub_interface  = stub_interface;
_buffer_size     = blob->content_size();
_buffer_limit    = blob->content_size();
_stub_buffer     = blob->content_begin();
_queue_begin     = 0;
_queue_end       = 0;
_number_of_stubs = 0;
}
```

## TemplateInterpreter



模板解释器相对于为每一个指令都写了一段实现对应功能的汇编代码，在JVM初始化时，汇编器会将汇编代码翻译成机器指令加载到内存中，比如执行iload指令时，直接执行对应的汇编代码即可。





模板解释器的大致逻辑主要分为以下几部分：

1. 为每个字节码创建模板；
2. 利用模板为每个字节码生成对应的机器指令；
3. 将每个字节码生成的机器指令地址存储在派发表中；
4. 在每个字节码生成的机器指令末尾，插入自动跳转下条指令逻辑。



下面就从模板解释器的初始化开始，分析HotSpot的解释代码的生成。
在创建虚拟机时，在[init_globals2](/docs/CS/Java/JDK/JVM/start.md?id=init_globals2)过程中，会调用interpreter_init()初始化模板解释器，
模板解释器的初始化包括抽象解释器AbstractInterpreter的初始化、模板表TemplateTable的初始化、CodeCache的Stub队列StubQueue的初始化、解释器生成器InterpreterGenerator的初始化


 

```c++
jint init_globals2() {
  universe2_init();          // dependent on codeCache_init and initial_stubs_init
  javaClasses_init();        // must happen after vtable initialization, before referenceProcessor_init
  interpreter_init_code();   // after javaClasses_init and before any method gets linked
  referenceProcessor_init();
  jni_handles_init();
#if INCLUDE_VM_STRUCTS
  vmStructs_init();
#endif // INCLUDE_VM_STRUCTS

  vtableStubs_init();
  InlineCacheBuffer_init();
  compilerOracle_init();
  dependencyContext_init();
  dependencies_init();

  if (!compileBroker_init()) {
    return JNI_EINVAL;
  }

  if (!universe_post_init()) {
    return JNI_ERR;
  }
  compiler_stubs_init(false /* in_compiler_thread */); // compiler's intrinsics stubs
  final_stubs_init();    // final StubRoutines stubs
  MethodHandles::generate_adapters();

  // All the flags that get adjusted by VM_Version_init and os::init_2
  // have been set so dump the flags now.
  if (PrintFlagsFinal || PrintFlagsRanges) {
    JVMFlag::printFlags(tty, false, PrintFlagsRanges);
  }

  return JNI_OK;
}
```

1.AbstractInterpreter是基于汇编模型的解释器的共同基类，定义了解释器和解释器生成器的抽象接口。 
2.模板表TemplateTable保存了各个字节码的模板(目标代码生成函数和参数)。 

TemplateTable的初始化调用def()将所有字节码的目标代码生成函数和参数保存在_template_table或_template_table_wide(wide指令)模板数组中

```c
void interpreter_init_code() {
  Interpreter::initialize_code();
  // need to hit every safepoint in order to call zapping routine
  // register the interpreter
  Forte::register_stub(
    "Interpreter",
    AbstractInterpreter::code()->code_start(),
    AbstractInterpreter::code()->code_end()
  );

  // notify JVMTI profiler
  if (JvmtiExport::should_post_dynamic_code_generated()) {
    JvmtiExport::post_dynamic_code_generated("Interpreter",
                                             AbstractInterpreter::code()->code_start(),
                                             AbstractInterpreter::code()->code_end());
  }
}
```



```c
void TemplateInterpreter::initialize_code() {
  AbstractInterpreter::initialize();

  TemplateTable::initialize();

  // generate interpreter
  { ResourceMark rm;
    TraceTime timer("Interpreter generation", TRACETIME_LOG(Info, startuptime));
    TemplateInterpreterGenerator g;
    // Free the unused memory not occupied by the interpreter and the stubs
    _code->deallocate_unused_tail();
  }

  if (PrintInterpreter) {
    ResourceMark rm;
    print();
  }

  // initialize dispatch table
  _active_table = _normal_table;
}
```

每个模板都关联其对应的汇编代码生成函数

```c

void TemplateTable::initialize() {

  // For better readability
  const char _    = ' ';
  const int  ____ = 0;
  const int  ubcp = 1 << Template::uses_bcp_bit;
  const int  disp = 1 << Template::does_dispatch_bit;
  const int  clvm = 1 << Template::calls_vm_bit;
  const int  iswd = 1 << Template::wide_bit;
  //                                    interpr. templates
  // Java spec bytecodes                ubcp|disp|clvm|iswd  in    out   generator             argument
  def(Bytecodes::_nop                 , ____|____|____|____, vtos, vtos, nop                 ,  _           );
  def(Bytecodes::_aconst_null         , ____|____|____|____, vtos, atos, aconst_null         ,  _           );
  //  ...
}
```

`def`函数其实就是用来创建模板的





在定义完成所有字节码对应的模板后，JVM会遍历所有字节码，为每个字节码生成对应的机器指令入口

```c
void TemplateInterpreterGenerator::set_entry_points_for_all_bytes() {
  for (int i = 0; i < DispatchTable::length; i++) {
    Bytecodes::Code code = (Bytecodes::Code)i;
    if (Bytecodes::is_defined(code)) {
      set_entry_points(code);
    } else {
      set_unimplemented(i);
    }
  }
}
```



set_entry_points()将取出该字节码对应的Template模板，并调用set_short_enrty_points()进行处理，并将入口地址保存在转发表(DispatchTable)_normal_table或_wentry_table(使用wide指令)中

```c
void TemplateInterpreterGenerator::set_entry_points(Bytecodes::Code code) {
  CodeletMark cm(_masm, Bytecodes::name(code), code);
  // initialize entry points
  assert(_unimplemented_bytecode    != nullptr, "should have been generated before");
  assert(_illegal_bytecode_sequence != nullptr, "should have been generated before");
  address bep = _illegal_bytecode_sequence;
  address zep = _illegal_bytecode_sequence;
  address cep = _illegal_bytecode_sequence;
  address sep = _illegal_bytecode_sequence;
  address aep = _illegal_bytecode_sequence;
  address iep = _illegal_bytecode_sequence;
  address lep = _illegal_bytecode_sequence;
  address fep = _illegal_bytecode_sequence;
  address dep = _illegal_bytecode_sequence;
  address vep = _unimplemented_bytecode;
  address wep = _unimplemented_bytecode;
  // code for short & wide version of bytecode
  if (Bytecodes::is_defined(code)) {
    Template* t = TemplateTable::template_for(code);
    assert(t->is_valid(), "just checking");
    set_short_entry_points(t, bep, cep, sep, aep, iep, lep, fep, dep, vep);
  }
  if (Bytecodes::wide_is_defined(code)) {
    Template* t = TemplateTable::template_for_wide(code);
    assert(t->is_valid(), "just checking");
    set_wide_entry_point(t, wep);
  }
  // set entry points
  EntryPoint entry(bep, zep, cep, sep, aep, iep, lep, fep, dep, vep);
  Interpreter::_normal_table.set_entry(code, entry);
  Interpreter::_wentry_point[code] = wep;
}
```



```c
void TemplateInterpreterGenerator::set_wide_entry_point(Template* t, address& wep) {
  assert(t->is_valid(), "template must exist");
  assert(t->tos_in() == vtos, "only vtos tos_in supported for wide instructions");
  wep = __ pc(); generate_and_dispatch(t);
}


void TemplateInterpreterGenerator::set_short_entry_points(Template* t, address& bep, address& cep, address& sep, address& aep, address& iep, address& lep, address& fep, address& dep, address& vep) {
  assert(t->is_valid(), "template must exist");
  switch (t->tos_in()) {
    case btos:
    case ztos:
    case ctos:
    case stos:
      ShouldNotReachHere();  // btos/ctos/stos should use itos.
      break;
    case atos: vep = __ pc(); __ pop(atos); aep = __ pc(); generate_and_dispatch(t); break;
    case itos: vep = __ pc(); __ pop(itos); iep = __ pc(); generate_and_dispatch(t); break;
    case ltos: vep = __ pc(); __ pop(ltos); lep = __ pc(); generate_and_dispatch(t); break;
    case ftos: vep = __ pc(); __ pop(ftos); fep = __ pc(); generate_and_dispatch(t); break;
    case dtos: vep = __ pc(); __ pop(dtos); dep = __ pc(); generate_and_dispatch(t); break;
    case vtos: set_vtos_entry_points(t, bep, cep, sep, aep, iep, lep, fep, dep, vep);     break;
    default  : ShouldNotReachHere();                                                 break;
  }
}
```

最终会调用TemplateInterpreterGenerator::generate_and_dispatch（）来生成机器指令

```c
void TemplateInterpreterGenerator::generate_and_dispatch(Template* t, TosState tos_out) {
#ifndef PRODUCT
  // debugging code
  if (CountBytecodes || TraceBytecodes || StopInterpreterAt > 0) count_bytecode();
  if (PrintBytecodeHistogram)                                    histogram_bytecode(t);
  if (PrintBytecodePairHistogram)                                histogram_bytecode_pair(t);
  if (TraceBytecodes)                                            trace_bytecode(t);
  if (StopInterpreterAt > 0)                                     stop_interpreter_at();
  __ verify_FPU(1, t->tos_in());
#endif // !PRODUCT
  int step = 0;
  if (!t->does_dispatch()) {
    step = t->is_wide() ? Bytecodes::wide_length_for(t->bytecode()) : Bytecodes::length_for(t->bytecode());
    if (tos_out == ilgl) tos_out = t->tos_out();
    // compute bytecode size
    assert(step > 0, "just checkin'");
    // setup stuff for dispatching next bytecode
    if (ProfileInterpreter && VerifyDataPointer
        && MethodData::bytecode_has_profile(t->bytecode())) {
      __ verify_method_data_pointer();
    }
    __ dispatch_prolog(tos_out, step);
  }
  // generate template
  t->generate(_masm);
  // advance
  if (t->does_dispatch()) {
#ifdef ASSERT
    // make sure execution doesn't go beyond this point if code is broken
    __ should_not_reach_here();
#endif // ASSERT
  } else {
    // dispatch to next bytecode
    __ dispatch_epilog(tos_out, step);
  }
}
```

在generate_and_dispatch（）中，会调用模版的generate（）方法，因为模板初始化时记录了对应的机器指令生成函数的指针，存在_gen中，所以这里直接调用_gen（）即可生成机器指令，对于iload来说，就相当于调用了TemplateTable::iload（）

```c
void Template::generate(InterpreterMacroAssembler* masm) {
  // parameter passing
  TemplateTable::_desc = this;
  TemplateTable::_masm = masm;
  // code generation
  _gen(_arg);
  masm->flush();
}
```





t->generate(_masm)后并没有立马撤走，而是会进行dispatch操作，调用 __ dispatch_epilog(tos_out, step)来进行下一条指令的执行，dispatch_epilog（）里面调用的是dispatch_next（）方法

```c
void InterpreterMacroAssembler::dispatch_epilog(TosState state, int step) {
    dispatch_next(state, step);
}

void InterpreterMacroAssembler::dispatch_next(TosState state, int step, bool generate_poll) {
  // load next bytecode
  ldrb(rscratch1, Address(pre(rbcp, step)));
  dispatch_base(state, Interpreter::dispatch_table(state), /*verifyoop*/true, generate_poll);
}
```



```c
void InterpreterMacroAssembler::dispatch_base(TosState state,
                                              address* table,
                                              bool verifyoop,
                                              bool generate_poll) {
  if (VerifyActivationFrameSize) {
    Unimplemented();
  }
  if (verifyoop) {
    interp_verify_oop(r0, state);
  }

  Label safepoint;
  address* const safepoint_table = Interpreter::safept_table(state);
  bool needs_thread_local_poll = generate_poll && table != safepoint_table;

  if (needs_thread_local_poll) {
    NOT_PRODUCT(block_comment("Thread-local Safepoint poll"));
    ldr(rscratch2, Address(rthread, JavaThread::polling_word_offset()));
    tbnz(rscratch2, exact_log2(SafepointMechanism::poll_bit()), safepoint);
  }

  if (table == Interpreter::dispatch_table(state)) {
    addw(rscratch2, rscratch1, Interpreter::distance_from_dispatch_table(state));
    ldr(rscratch2, Address(rdispatch, rscratch2, Address::uxtw(3)));
  } else {
    mov(rscratch2, (address)table);
    ldr(rscratch2, Address(rscratch2, rscratch1, Address::uxtw(3)));
  }
  br(rscratch2);

  if (needs_thread_local_poll) {
    bind(safepoint);
    lea(rscratch2, ExternalAddress((address)safepoint_table));
    ldr(rscratch2, Address(rscratch2, rscratch1, Address::uxtw(3)));
    br(rscratch2);
  }
}
```











The division of labor is as follows:

- Template Interpreter          Zero Interpreter       Functionality
- templateTable*                bytecodeInterpreter*   actual interpretation of bytecodes
- templateInterpreter*          zeroInterpreter*       generation of assembly code that creates and manages interpreter runtime frames.

```cpp
// share/interpreter/templateInterpreter.hpp
class TemplateInterpreter: public AbstractInterpreter {
 protected:

  static address    _throw_ArrayIndexOutOfBoundsException_entry;
  static address    _throw_ArrayStoreException_entry;
  static address    _throw_ArithmeticException_entry;
  static address    _throw_ClassCastException_entry;
  static address    _throw_NullPointerException_entry;
  static address    _throw_exception_entry;

  static address    _throw_StackOverflowError_entry;

  static address    _remove_activation_entry;                   // continuation address if an exception is not handled by current frame
  static address    _remove_activation_preserving_args_entry;   // continuation address when current frame is being popped

  static EntryPoint _trace_code;
  static EntryPoint _return_entry[number_of_return_entries];    // entry points to return to from a call
  static EntryPoint _earlyret_entry;                            // entry point to return early from a call
  static EntryPoint _deopt_entry[number_of_deopt_entries];      // entry points to return to from a deoptimization
  static address    _deopt_reexecute_return_entry;
  static EntryPoint _safept_entry;

  static address _invoke_return_entry[number_of_return_addrs];           // for invokestatic, invokespecial, invokevirtual return entries
  static address _invokeinterface_return_entry[number_of_return_addrs];  // for invokeinterface return entries
  static address _invokedynamic_return_entry[number_of_return_addrs];    // for invokedynamic return entries

  static DispatchTable _active_table;                           // the active    dispatch table (used by the interpreter for dispatch)
  static DispatchTable _normal_table;                           // the normal    dispatch table (used to set the active table in normal mode)
  static DispatchTable _safept_table;                           // the safepoint dispatch table (used to set the active table for safepoints)
  static address       _wentry_point[DispatchTable::length];    // wide instructions only (vtos tosca always)
}
```

```cpp
TemplateInterpreterGenerator::TemplateInterpreterGenerator(StubQueue* _code): AbstractInterpreterGenerator(_code) {
  _unimplemented_bytecode    = NULL;
  _illegal_bytecode_sequence = NULL;
  generate_all();
}
```

## init

The reason that interpreter initialization is split into two parts is that the first part needs to run before methods are loaded (which with CDS implies linked also),
and the other part needs to run after.
The reason is that when methods are loaded (with CDS) or linked(without CDS),
the i2c adapters are generated that assert we are currently in the interpreter.

Asserting that requires knowledge about where the interpreter is in memory.
Therefore, establishing the interpreter address must be done before methods are loaded.
However, we would like to actually generate the interpreter after methods are loaded.
That allows us to remove otherwise hardcoded offsets regarding fields that are needed in the interpreter code.

This leads to a split like:

1. reserving the memory for the interpreter
2. loading methods
3. generating the interpreter

### init_stub

allocate interpreter and new StubQueue

```cpp
void interpreter_init_stub() {
  Interpreter::initialize_stub();
}

void TemplateInterpreter::initialize_stub() {
  // assertions
  assert(_code == NULL, "must only initialize once");
  assert((int)Bytecodes::number_of_codes <= (int)DispatchTable::length,
         "dispatch table too small");

  // allocate interpreter
  int code_size = InterpreterCodeSize;
  NOT_PRODUCT(code_size *= 4;)  // debug uses extra interpreter code space
  _code = new StubQueue(new InterpreterCodeletInterface, code_size, NULL,
                        "Interpreter");
}
```

### init_code

```cpp

void interpreter_init_code() {
  Interpreter::initialize_code();
#ifndef PRODUCT
  if (TraceBytecodes) BytecodeTracer::set_closure(BytecodeTracer::std_closure());
#endif // PRODUCT
  // need to hit every safepoint in order to call zapping routine
  // register the interpreter
  Forte::register_stub(
    "Interpreter",
    AbstractInterpreter::code()->code_start(),
    AbstractInterpreter::code()->code_end()
  );

  // notify JVMTI profiler
  if (JvmtiExport::should_post_dynamic_code_generated()) {
    JvmtiExport::post_dynamic_code_generated("Interpreter",
                                             AbstractInterpreter::code()->code_start(),
                                             AbstractInterpreter::code()->code_end());
  }
}
```

```cpp

void TemplateInterpreter::initialize_code() {
  AbstractInterpreter::initialize();

  TemplateTable::initialize();
```

TemplateInterpreterGenerator::generate_all -> TemplateInterpreterGenerator::generate_method_entry -> generate_native_entry/generate_normal_entry(different arch)

- [generate_native_entry](/docs/CS/Java/JDK/JVM/interpreter.md?id=generate_native_entry) -- need to unlock manually after call native method
- [generate_normal_entry](/docs/CS/Java/JDK/JVM/interpreter.md?id=generate_normal_entry) -- using dispatch_next(), some bytecode(`return`,`athrow`) will unlock

```cpp
  { ResourceMark rm;
    TraceTime timer("Interpreter generation", TRACETIME_LOG(Info, startuptime));
    TemplateInterpreterGenerator g(_code);
    // Free the unused memory not occupied by the interpreter and the stubs
    _code->deallocate_unused_tail();
  }

  if (PrintInterpreter) {
    ResourceMark rm;
    print();
  }

  // initialize dispatch table
  _active_table = _normal_table;
}
```

### generate_normal_entry

Generic interpreted method entry to (asm) interpreter

Such as x86

```cpp
// cpu/x86/templateInterpreterGenerator_x86.cpp
address TemplateInterpreterGenerator::generate_normal_entry(bool synchronized) {
  // determine code generation flags
  bool inc_counter  = UseCompiler || CountCompiledCalls || LogTouchedMethods;

  // ebx: Method*
  // rbcp: sender sp
  address entry_point = __ pc();

  const Address constMethod(rbx, Method::const_offset());
  const Address access_flags(rbx, Method::access_flags_offset());
  const Address size_of_parameters(rdx,
                                   ConstMethod::size_of_parameters_offset());
  const Address size_of_locals(rdx, ConstMethod::size_of_locals_offset());


  // get parameter size (always needed)
  __ movptr(rdx, constMethod);
  __ load_unsigned_short(rcx, size_of_parameters);

  // rbx: Method*
  // rcx: size of parameters
  // rbcp: sender_sp (could differ from sp+wordSize if we were called via c2i )

  __ load_unsigned_short(rdx, size_of_locals); // get size of locals in words
  __ subl(rdx, rcx); // rdx = no. of additional locals

  // YYY
  //   __ incrementl(rdx);
  //   __ andl(rdx, -2);

  // see if we've got enough room on the stack for locals plus overhead.
  generate_stack_overflow_check();

  // get return address
  __ pop(rax);

  // compute beginning of parameters
  __ lea(rlocals, Address(rsp, rcx, Interpreter::stackElementScale(), -wordSize));

  // rdx - # of additional locals
  // allocate space for locals
  // explicitly initialize locals
  {
    Label exit, loop;
    __ testl(rdx, rdx);
    __ jcc(Assembler::lessEqual, exit); // do nothing if rdx <= 0
    __ bind(loop);
    __ push((int) NULL_WORD); // initialize local variables
    __ decrementl(rdx); // until everything initialized
    __ jcc(Assembler::greater, loop);
    __ bind(exit);
  }
```

initialize fixed part of activation frame

```cpp
  generate_fixed_frame(false);

  // make sure method is not native & not abstract


  // Since at this point in the method invocation the exception
  // handler would try to exit the monitor of synchronized methods
  // which hasn't been entered yet, we set the thread local variable
  // _do_not_unlock_if_synchronized to true. The remove_activation
  // will check this flag.

  const Register thread = NOT_LP64(rax) LP64_ONLY(r15_thread);
  NOT_LP64(__ get_thread(thread));
  const Address do_not_unlock_if_synchronized(thread,
        in_bytes(JavaThread::do_not_unlock_if_synchronized_offset()));
  __ movbool(do_not_unlock_if_synchronized, true);

  __ profile_parameters_type(rax, rcx, rdx);
```

increment invocation count & check for overflow

```cpp
  Label invocation_counter_overflow;
  if (inc_counter) {
    generate_counter_incr(&invocation_counter_overflow);
  }

  Label continue_after_compile;
  __ bind(continue_after_compile);

  // check for synchronized interpreted methods
  bang_stack_shadow_pages(false);

  // reset the _do_not_unlock_if_synchronized flag
  NOT_LP64(__ get_thread(thread));
  __ movbool(do_not_unlock_if_synchronized, false);
```

check for synchronized methods
Must happen AFTER invocation_counter check and stack overflow check, so method is not locked if overflows.

```cpp
  if (synchronized) {
```

Allocate monitor and [lock method](/docs/CS/Java/JDK/JVM/interpreter.md?id=lock_method)

```cpp
    lock_method();
  } else {
    // no synchronization necessary
  }

  // start execution


  // jvmti support
  __ notify_method_entry();

  __ dispatch_next(vtos);

  // invocation counter overflow
  if (inc_counter) {
    // Handle overflow of counter and compile method
    __ bind(invocation_counter_overflow);
    generate_counter_overflow(continue_after_compile);
  }

  return entry_point;
}
```

#### dispatch_next

```cpp

void InterpreterMacroAssembler::dispatch_next(TosState state, int step, bool generate_poll) {
  // load next bytecode (load before advancing _bcp_register to prevent AGI)
  load_unsigned_byte(rbx, Address(_bcp_register, step));
  // advance _bcp_register
  increment(_bcp_register, step);
  dispatch_base(state, Interpreter::dispatch_table(state), true, generate_poll);
}


void InterpreterMacroAssembler::dispatch_base(TosState state,
                                              address* table,
                                              bool verifyoop,
                                              bool generate_poll) {
  verify_FPU(1, state);
  if (VerifyActivationFrameSize) {
    Label L;
    mov(rcx, rbp);
    subptr(rcx, rsp);
    int32_t min_frame_size =
      (frame::link_offset - frame::interpreter_frame_initial_sp_offset) *
      wordSize;
    cmpptr(rcx, (int32_t)min_frame_size);
    jcc(Assembler::greaterEqual, L);
    stop("broken stack frame");
    bind(L);
  }
  if (verifyoop) {
    interp_verify_oop(rax, state);
  }
```

Check if need [SafePoint](/docs/CS/Java/JDK/JVM/Safepoint.md) then jump into safepoint_table.

```cpp
  address* const safepoint_table = Interpreter::safept_table(state);

  Label no_safepoint, dispatch;
  if (table != safepoint_table && generate_poll) {
    NOT_PRODUCT(block_comment("Thread-local Safepoint poll"));
    testb(Address(r15_thread, JavaThread::polling_word_offset()), SafepointMechanism::poll_bit());

    jccb(Assembler::zero, no_safepoint);
    lea(rscratch1, ExternalAddress((address)safepoint_table));
    jmpb(dispatch);
  }
```

Or else jump into normal table.

```cpp
  bind(no_safepoint);
  lea(rscratch1, ExternalAddress((address)table));
  bind(dispatch);
  jmp(Address(rscratch1, rbx, Address::times_8));
}
```

#### lock_method

Allocate monitor and lock method (asm interpreter) , see [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md).

Args:

- rbx: Method*
- r14/rdi: locals
- Kills:
- rax
- c_rarg0, c_rarg1, c_rarg2, c_rarg3, ...(param regs)
- rscratch1, rscratch2 (scratch regs)

```cpp
// cpu/x86/templateInterpreterGenerator_x86.cpp
void TemplateInterpreterGenerator::lock_method() {
  // synchronize method
  const Address access_flags(rbx, Method::access_flags_offset());
  const Address monitor_block_top(
        rbp,
        frame::interpreter_frame_monitor_block_top_offset * wordSize);
  const int entry_size = frame::interpreter_frame_monitor_size() * wordSize;

  // get synchronization object
  {
    Label done;
    __ movl(rax, access_flags);
    __ testl(rax, JVM_ACC_STATIC);
    // get receiver (assume this is frequent case)
    __ movptr(rax, Address(rlocals, Interpreter::local_offset_in_bytes(0)));
    __ jcc(Assembler::zero, done);
    __ load_mirror(rax, rbx);

    __ bind(done);
  }

  // add space for monitor & lock
  __ subptr(rsp, entry_size); // add space for a monitor entry
  __ movptr(monitor_block_top, rsp);  // set new monitor block top
  // store object
  __ movptr(Address(rsp, BasicObjectLock::obj_offset_in_bytes()), rax);
  const Register lockreg = NOT_LP64(rdx) LP64_ONLY(c_rarg1);
  __ movptr(lockreg, rsp); // object address
```

lock object

```cpp
  __ lock_object(lockreg);
}
```

##### lock_object

Args:
rdx, c_rarg1: BasicObjectLock to be used for locking

Kills:
rax, rbx

```cpp
// interp_masm_x86.cpp
void InterpreterMacroAssembler::lock_object(Register lock_reg) {

  if (UseHeavyMonitors) {
    call_VM(noreg,
            CAST_FROM_FN_PTR(address, InterpreterRuntime::monitorenter),
            lock_reg);
  } else {
    Label done;

    const Register swap_reg = rax; // Must use rax for cmpxchg instruction
    const Register tmp_reg = rbx;
    const Register obj_reg = LP64_ONLY(c_rarg3) NOT_LP64(rcx); // Will contain the oop
    const Register rklass_decode_tmp = LP64_ONLY(rscratch1) NOT_LP64(noreg);

    const int obj_offset = BasicObjectLock::obj_offset_in_bytes();
    const int lock_offset = BasicObjectLock::lock_offset_in_bytes ();
    const int mark_offset = lock_offset +
                            BasicLock::displaced_header_offset_in_bytes();

    Label slow_case;
```

Load object pointer into obj_reg

```cpp
    movptr(obj_reg, Address(lock_reg, obj_offset));

    if (DiagnoseSyncOnValueBasedClasses != 0) {
      load_klass(tmp_reg, obj_reg, rklass_decode_tmp);
      movl(tmp_reg, Address(tmp_reg, Klass::access_flags_offset()));
      testl(tmp_reg, JVM_ACC_IS_VALUE_BASED_CLASS);
      jcc(Assembler::notZero, slow_case);
    }

    // Load immediate 1 into swap_reg %rax
    movl(swap_reg, (int32_t)1);

```

1. Load (object->mark() | 1) into swap_reg %rax
2. Save (object->mark() | 1) into BasicLock's displaced header

```cpp
    orptr(swap_reg, Address(obj_reg, oopDesc::mark_offset_in_bytes()));
    movptr(Address(lock_reg, mark_offset), swap_reg);
    lock();
    cmpxchgptr(lock_reg, Address(obj_reg, oopDesc::mark_offset_in_bytes()));
    jcc(Assembler::zero, done);

    const int zero_bits = LP64_ONLY(7) NOT_LP64(3);
```

Fast check for recursive lock.

Can apply the optimization only if this is a stack lock
allocated in this thread. For efficiency, we can focus on
recently allocated stack locks (instead of reading the stack
base and checking whether 'mark' points inside the current
thread stack):

1) (mark & zero_bits) == 0, and
2) rsp <= mark < mark + os::pagesize()

Warning: rsp + os::pagesize can overflow the stack base. We must
neither apply the optimization for an inflated lock allocated
just above the thread stack (this is why condition 1 matters)
nor apply the optimization if the stack lock is inside the stack
of another thread. The latter is avoided even in case of overflow
because we have guard pages at the end of all stacks. Hence, if
we go over the stack base and hit the stack of another thread,
this should not be in a writeable area that could contain a
stack lock allocated by that thread. As a consequence, a stack
lock less than page size away from rsp is guaranteed to be
owned by the current thread.

These 3 tests can be done by evaluating the following
expression: ((mark - rsp) & (zero_bits - os::vm_page_size())),
assuming both stack pointer and pagesize have their
least significant bits clear.
NOTE: the mark is in swap_reg %rax as the result of cmpxchg

```cpp
    subptr(swap_reg, rsp);
    andptr(swap_reg, zero_bits - os::vm_page_size());
```

Save the test result, for recursive case, the result is zero

```cpp
    movptr(Address(lock_reg, mark_offset), swap_reg);
    jcc(Assembler::zero, done);

    bind(slow_case);
```

Call the runtime routine for slow case

```cpp
    call_VM(noreg,
            CAST_FROM_FN_PTR(address, InterpreterRuntime::monitorenter),
            lock_reg);

    bind(done);
  }
}
```

### generate_native_entry

Interpreter stub for calling a native method. (asm interpreter)
This sets up a somewhat different looking stack for calling the native method than the typical interpreter frame setup.

```c
// 
address TemplateInterpreterGenerator::generate_native_entry(bool synchronized) {
  // determine code generation flags
  bool inc_counter  = UseCompiler || CountCompiledCalls || LogTouchedMethods;

  // rbx: Method*
  // rbcp: sender sp

  address entry_point = __ pc();

  const Address constMethod       (rbx, Method::const_offset());
  const Address access_flags      (rbx, Method::access_flags_offset());
  const Address size_of_parameters(rcx, ConstMethod::
                                        size_of_parameters_offset());


  // get parameter size (always needed)
  __ movptr(rcx, constMethod);
  __ load_unsigned_short(rcx, size_of_parameters);
```

native calls don't need the stack size check since they have no
expression stack and the arguments are already on the stack
and we only add a handful of words to the stack

- rbx: Method*
- rcx: size of parameters
- rbcp: sender sp

```cpp
  __ pop(rax);                                       // get return address

  // for natives the size of locals is zero

  // compute beginning of parameters
  __ lea(rlocals, Address(rsp, rcx, Interpreter::stackElementScale(), -wordSize));

  // add 2 zero-initialized slots for native calls
  // initialize result_handler slot
  __ push((int) NULL_WORD);
  // slot for oop temp
  // (static native method holder mirror/jni oop result)
  __ push((int) NULL_WORD);

  // initialize fixed part of activation frame
  generate_fixed_frame(true);

  // make sure method is native & not abstract

  // Since at this point in the method invocation the exception handler
  // would try to exit the monitor of synchronized methods which hasn't
  // been entered yet, we set the thread local variable
  // _do_not_unlock_if_synchronized to true. The remove_activation will
  // check this flag.

  const Register thread1 = NOT_LP64(rax) LP64_ONLY(r15_thread);
  NOT_LP64(__ get_thread(thread1));
  const Address do_not_unlock_if_synchronized(thread1,
        in_bytes(JavaThread::do_not_unlock_if_synchronized_offset()));
  __ movbool(do_not_unlock_if_synchronized, true);

  // increment invocation count & check for overflow
  Label invocation_counter_overflow;
  if (inc_counter) {
    generate_counter_incr(&invocation_counter_overflow);
  }

  Label continue_after_compile;
  __ bind(continue_after_compile);

  bang_stack_shadow_pages(true);

  // reset the _do_not_unlock_if_synchronized flag
  NOT_LP64(__ get_thread(thread1));
  __ movbool(do_not_unlock_if_synchronized, false);

  // check for synchronized methods
  // Must happen AFTER invocation_counter check and stack overflow check,
  // so method is not locked if overflows.
  if (synchronized) {
    lock_method();
  } else {
    // no synchronization necessary
  }

  // start execution

  // jvmti support
  __ notify_method_entry();

  // work registers
  const Register method = rbx;
  const Register thread = NOT_LP64(rdi) LP64_ONLY(r15_thread);
  const Register t      = NOT_LP64(rcx) LP64_ONLY(r11);

  // allocate space for parameters
  __ get_method(method);
  __ movptr(t, Address(method, Method::const_offset()));
  __ load_unsigned_short(t, Address(t, ConstMethod::size_of_parameters_offset()));

  #ifndef _LP64
  __ shlptr(t, Interpreter::logStackElementSize); // Convert parameter count to bytes.
  __ addptr(t, 2*wordSize);     // allocate two more slots for JNIEnv and possible mirror
  __ subptr(rsp, t);
  __ andptr(rsp, -(StackAlignmentInBytes)); // gcc needs 16 byte aligned stacks to do XMM intrinsics
  #else
  __ shll(t, Interpreter::logStackElementSize);

  __ subptr(rsp, t);
  __ subptr(rsp, frame::arg_reg_save_area_bytes); // windows
  __ andptr(rsp, -16); // must be 16 byte boundary (see amd64 ABI)
  #endif // _LP64

  // get signature handler
  {
    Label L;
    __ movptr(t, Address(method, Method::signature_handler_offset()));
    __ testptr(t, t);
    __ jcc(Assembler::notZero, L);
    __ call_VM(noreg,
               CAST_FROM_FN_PTR(address,
                                InterpreterRuntime::prepare_native_call),
               method);
    __ get_method(method);
    __ movptr(t, Address(method, Method::signature_handler_offset()));
    __ bind(L);
  }

  // call signature handler
  assert(InterpreterRuntime::SignatureHandlerGenerator::from() == rlocals,
         "adjust this code");
  assert(InterpreterRuntime::SignatureHandlerGenerator::to() == rsp,
         "adjust this code");
  assert(InterpreterRuntime::SignatureHandlerGenerator::temp() == NOT_LP64(t) LP64_ONLY(rscratch1),
         "adjust this code");

  // The generated handlers do not touch RBX (the method).
  // However, large signatures cannot be cached and are generated
  // each time here.  The slow-path generator can do a GC on return,
  // so we must reload it after the call.
  __ call(t);
  __ get_method(method);        // slow path can do a GC, reload RBX

  // result handler is in rax
  // set result handler
  __ movptr(Address(rbp,
                    (frame::interpreter_frame_result_handler_offset) * wordSize),
            rax);

  // pass mirror handle if static call
  {
    Label L;
    __ movl(t, Address(method, Method::access_flags_offset()));
    __ testl(t, JVM_ACC_STATIC);
    __ jcc(Assembler::zero, L);
    // get mirror
    __ load_mirror(t, method, rax);
    // copy mirror into activation frame
    __ movptr(Address(rbp, frame::interpreter_frame_oop_temp_offset * wordSize),
            t);
    // pass handle to mirror
  #ifndef _LP64
    __ lea(t, Address(rbp, frame::interpreter_frame_oop_temp_offset * wordSize));
    __ movptr(Address(rsp, wordSize), t);
  #else
    __ lea(c_rarg1,
           Address(rbp, frame::interpreter_frame_oop_temp_offset * wordSize));
  #endif // _LP64
    __ bind(L);
  }

  // get native function entry point
  {
    Label L;
    __ movptr(rax, Address(method, Method::native_function_offset()));
    ExternalAddress unsatisfied(SharedRuntime::native_method_throw_unsatisfied_link_error_entry());
    __ cmpptr(rax, unsatisfied.addr());
    __ jcc(Assembler::notEqual, L);
    __ call_VM(noreg,
               CAST_FROM_FN_PTR(address,
                                InterpreterRuntime::prepare_native_call),
               method);
    __ get_method(method);
    __ movptr(rax, Address(method, Method::native_function_offset()));
    __ bind(L);
  }

  // pass JNIEnv
  #ifndef _LP64
   __ get_thread(thread);
   __ lea(t, Address(thread, JavaThread::jni_environment_offset()));
   __ movptr(Address(rsp, 0), t);

   // set_last_Java_frame_before_call
   // It is enough that the pc()
   // points into the right code segment. It does not have to be the correct return pc.
   __ set_last_Java_frame(thread, noreg, rbp, __ pc());
  #else
   __ lea(c_rarg0, Address(r15_thread, JavaThread::jni_environment_offset()));

   // It is enough that the pc() points into the right code
   // segment. It does not have to be the correct return pc.
   __ set_last_Java_frame(rsp, rbp, (address) __ pc());
  #endif // _LP64

  // change thread state

  // Change state to native

  __ movl(Address(thread, JavaThread::thread_state_offset()),
          _thread_in_native);
```

Call the native method.

```cpp
  __ call(rax);
  // 32: result potentially in rdx:rax or ST0
  // 64: result potentially in rax or xmm0

  // Verify or restore cpu control state after JNI call
  __ restore_cpu_control_state_after_jni();

  // NOTE: The order of these pushes is known to frame::interpreter_frame_result
  // in order to extract the result of a method call. If the order of these
  // pushes change or anything else is added to the stack then the code in
  // interpreter_frame_result must also change.

  #ifndef _LP64
  // save potential result in ST(0) & rdx:rax
  // (if result handler is the T_FLOAT or T_DOUBLE handler, result must be in ST0 -
  // the check is necessary to avoid potential Intel FPU overflow problems by saving/restoring 'empty' FPU registers)
  // It is safe to do this push because state is _thread_in_native and return address will be found
  // via _last_native_pc and not via _last_jave_sp

  // NOTE: the order of theses push(es) is known to frame::interpreter_frame_result.
  // If the order changes or anything else is added to the stack the code in
  // interpreter_frame_result will have to be changed.

  { Label L;
    Label push_double;
    ExternalAddress float_handler(AbstractInterpreter::result_handler(T_FLOAT));
    ExternalAddress double_handler(AbstractInterpreter::result_handler(T_DOUBLE));
    __ cmpptr(Address(rbp, (frame::interpreter_frame_oop_temp_offset + 1)*wordSize),
              float_handler.addr());
    __ jcc(Assembler::equal, push_double);
    __ cmpptr(Address(rbp, (frame::interpreter_frame_oop_temp_offset + 1)*wordSize),
              double_handler.addr());
    __ jcc(Assembler::notEqual, L);
    __ bind(push_double);
    __ push_d(); // FP values are returned using the FPU, so push FPU contents (even if UseSSE > 0).
    __ bind(L);
  }
  #else
  __ push(dtos);
  #endif // _LP64

  __ push(ltos);

  // change thread state
  NOT_LP64(__ get_thread(thread));
  __ movl(Address(thread, JavaThread::thread_state_offset()),
          _thread_in_native_trans);

  // Force this write out before the read below
  __ membar(Assembler::Membar_mask_bits(
              Assembler::LoadLoad | Assembler::LoadStore |
              Assembler::StoreLoad | Assembler::StoreStore));

  #ifndef _LP64
  if (AlwaysRestoreFPU) {
    //  Make sure the control word is correct.
    __ fldcw(ExternalAddress(StubRoutines::x86::addr_fpu_cntrl_wrd_std()));
  }
  #endif // _LP64

  // check for safepoint operation in progress and/or pending suspend requests
  {
    Label Continue;
    Label slow_path;

    __ safepoint_poll(slow_path, thread, true /* at_return */, false /* in_nmethod */);

    __ cmpl(Address(thread, JavaThread::suspend_flags_offset()), 0);
    __ jcc(Assembler::equal, Continue);
    __ bind(slow_path);

    // Don't use call_VM as it will see a possible pending exception
    // and forward it and never return here preventing us from
    // clearing _last_native_pc down below.  Also can't use
    // call_VM_leaf either as it will check to see if r13 & r14 are
    // preserved and correspond to the bcp/locals pointers. So we do a
    // runtime call by hand.
    //
  #ifndef _LP64
    __ push(thread);
    __ call(RuntimeAddress(CAST_FROM_FN_PTR(address,
                                            JavaThread::check_special_condition_for_native_trans)));
    __ increment(rsp, wordSize);
    __ get_thread(thread);
  #else
    __ mov(c_rarg0, r15_thread);
    __ mov(r12, rsp); // remember sp (can only use r12 if not using call_VM)
    __ subptr(rsp, frame::arg_reg_save_area_bytes); // windows
    __ andptr(rsp, -16); // align stack as required by ABI
    __ call(RuntimeAddress(CAST_FROM_FN_PTR(address, JavaThread::check_special_condition_for_native_trans)));
    __ mov(rsp, r12); // restore sp
    __ reinit_heapbase();
  #endif // _LP64
    __ bind(Continue);
  }

  // change thread state
  __ movl(Address(thread, JavaThread::thread_state_offset()), _thread_in_Java);

  // reset_last_Java_frame
  __ reset_last_Java_frame(thread, true);

  if (CheckJNICalls) {
    // clear_pending_jni_exception_check
    __ movptr(Address(thread, JavaThread::pending_jni_exception_check_fn_offset()), NULL_WORD);
  }

  // reset handle block
  __ movptr(t, Address(thread, JavaThread::active_handles_offset()));
  __ movl(Address(t, JNIHandleBlock::top_offset_in_bytes()), (int32_t)NULL_WORD);

  // If result is an oop unbox and store it in frame where gc will see it
  // and result handler will pick it up

  {
    Label no_oop;
    __ lea(t, ExternalAddress(AbstractInterpreter::result_handler(T_OBJECT)));
    __ cmpptr(t, Address(rbp, frame::interpreter_frame_result_handler_offset*wordSize));
    __ jcc(Assembler::notEqual, no_oop);
    // retrieve result
    __ pop(ltos);
    // Unbox oop result, e.g. JNIHandles::resolve value.
    __ resolve_jobject(rax /* value */,
                       thread /* thread */,
                       t /* tmp */);
    __ movptr(Address(rbp, frame::interpreter_frame_oop_temp_offset*wordSize), rax);
    // keep stack depth as expected by pushing oop which will eventually be discarded
    __ push(ltos);
    __ bind(no_oop);
  }

  {
    Label no_reguard;
    __ cmpl(Address(thread, JavaThread::stack_guard_state_offset()),
            StackOverflow::stack_guard_yellow_reserved_disabled);
    __ jcc(Assembler::notEqual, no_reguard);

    __ pusha(); // XXX only save smashed registers
  #ifndef _LP64
    __ call(RuntimeAddress(CAST_FROM_FN_PTR(address, SharedRuntime::reguard_yellow_pages)));
    __ popa();
  #else
    __ mov(r12, rsp); // remember sp (can only use r12 if not using call_VM)
    __ subptr(rsp, frame::arg_reg_save_area_bytes); // windows
    __ andptr(rsp, -16); // align stack as required by ABI
    __ call(RuntimeAddress(CAST_FROM_FN_PTR(address, SharedRuntime::reguard_yellow_pages)));
    __ mov(rsp, r12); // restore sp
    __ popa(); // XXX only restore smashed registers
    __ reinit_heapbase();
  #endif // _LP64

    __ bind(no_reguard);
  }

  // The method register is junk from after the thread_in_native transition
  // until here.  Also can't call_VM until the bcp has been
  // restored.  Need bcp for throwing exception below so get it now.
  __ get_method(method);

  // restore to have legal interpreter frame, i.e., bci == 0 <=> code_base()
  __ movptr(rbcp, Address(method, Method::const_offset()));   // get ConstMethod*
  __ lea(rbcp, Address(rbcp, ConstMethod::codes_offset()));    // get codebase

  // handle exceptions (exception handling will handle unlocking!)
  {
    Label L;
    __ cmpptr(Address(thread, Thread::pending_exception_offset()), (int32_t) NULL_WORD);
    __ jcc(Assembler::zero, L);
    // Note: At some point we may want to unify this with the code
    // used in call_VM_base(); i.e., we should use the
    // StubRoutines::forward_exception code. For now this doesn't work
    // here because the rsp is not correctly set at this point.
    __ MacroAssembler::call_VM(noreg,
                               CAST_FROM_FN_PTR(address,
                               InterpreterRuntime::throw_pending_exception));
    __ should_not_reach_here();
    __ bind(L);
  }

  // do unlocking if necessary
  {
    Label L;
    __ movl(t, Address(method, Method::access_flags_offset()));
    __ testl(t, JVM_ACC_SYNCHRONIZED);
    __ jcc(Assembler::zero, L);
    // the code below should be shared with interpreter macro
    // assembler implementation
    {
      Label unlock;
      // BasicObjectLock will be first in list, since this is a
      // synchronized method. However, need to check that the object
      // has not been unlocked by an explicit monitorexit bytecode.
      const Address monitor(rbp,
                            (intptr_t)(frame::interpreter_frame_initial_sp_offset *
                                       wordSize - (int)sizeof(BasicObjectLock)));

      const Register regmon = NOT_LP64(rdx) LP64_ONLY(c_rarg1);

      // monitor expect in c_rarg1 for slow unlock path
      __ lea(regmon, monitor); // address of first monitor

      __ movptr(t, Address(regmon, BasicObjectLock::obj_offset_in_bytes()));
      __ testptr(t, t);
      __ jcc(Assembler::notZero, unlock);

      // Entry already unlocked, need to throw exception
      __ MacroAssembler::call_VM(noreg,
                                 CAST_FROM_FN_PTR(address,
                   InterpreterRuntime::throw_illegal_monitor_state_exception));
      __ should_not_reach_here();

      __ bind(unlock);
      __ unlock_object(regmon);
    }
    __ bind(L);
  }

  // jvmti support
  // Note: This must happen _after_ handling/throwing any exceptions since
  //       the exception handler code notifies the runtime of method exits
  //       too. If this happens before, method entry/exit notifications are
  //       not properly paired (was bug - gri 11/22/99).
  __ notify_method_exit(vtos, InterpreterMacroAssembler::NotifyJVMTI);

  // restore potential result in edx:eax, call result handler to
  // restore potential result in ST0 & handle result

  __ pop(ltos);
  LP64_ONLY( __ pop(dtos));

  __ movptr(t, Address(rbp,
                       (frame::interpreter_frame_result_handler_offset) * wordSize));
  __ call(t);

  // remove activation
  __ movptr(t, Address(rbp,
                       frame::interpreter_frame_sender_sp_offset *
                       wordSize)); // get sender sp
  __ leave();                                // remove frame anchor
  __ pop(rdi);                               // get return address
  __ mov(rsp, t);                            // set sp to sender sp
  __ jmp(rdi);

  if (inc_counter) {
    // Handle overflow of counter and compile method
    __ bind(invocation_counter_overflow);
    generate_counter_overflow(continue_after_compile);
  }

  return entry_point;
}
```

## code

Method Counter and backedge counter are using profiling.

### branch

```cpp
// cpu/x86/templateInterpreterGenerator_x86.cpp
void TemplateTable::if_icmp(Condition cc) {
  transition(itos, vtos);
  // assume branch is more often taken than not (loops use backward branches)
  Label not_taken;
  __ pop_i(rdx);
  __ cmpl(rdx, rax);
  __ jcc(j_not(cc), not_taken);
  branch(false, false);
  __ bind(not_taken);
  __ profile_not_taken_branch(rax);
}
```

branch

```cpp

void TemplateTable::branch(bool is_jsr, bool is_wide) {
  __ get_method(rcx); // rcx holds method
  __ profile_taken_branch(rax, rbx); // rax holds updated MDP, rbx
                                     // holds bumped taken count

  const ByteSize be_offset = MethodCounters::backedge_counter_offset() +
                             InvocationCounter::counter_offset();
  const ByteSize inv_offset = MethodCounters::invocation_counter_offset() +
                              InvocationCounter::counter_offset();

  // Load up edx with the branch displacement
  if (is_wide) {
    __ movl(rdx, at_bcp(1));
  } else {
    __ load_signed_short(rdx, at_bcp(1));
  }
  __ bswapl(rdx);

  if (!is_wide) {
    __ sarl(rdx, 16);
  }
  LP64_ONLY(__ movl2ptr(rdx, rdx));

  // Handle all the JSR stuff here, then exit.
  // It's much shorter and cleaner than intermingling with the non-JSR
  // normal-branch stuff occurring below.
  if (is_jsr) {
    // Pre-load the next target bytecode into rbx
    __ load_unsigned_byte(rbx, Address(rbcp, rdx, Address::times_1, 0));

    // compute return address as bci in rax
    __ lea(rax, at_bcp((is_wide ? 5 : 3) -
                        in_bytes(ConstMethod::codes_offset())));
    __ subptr(rax, Address(rcx, Method::const_offset()));
    // Adjust the bcp in r13 by the displacement in rdx
    __ addptr(rbcp, rdx);
    // jsr returns atos that is not an oop
    __ push_i(rax);
    __ dispatch_only(vtos, true);
    return;
  }

  // Normal (non-jsr) branch handling

  // Adjust the bcp in r13 by the displacement in rdx
  __ addptr(rbcp, rdx);

  assert(UseLoopCounter || !UseOnStackReplacement,
         "on-stack-replacement requires loop counters");
  Label backedge_counter_overflow;
  Label dispatch;
  if (UseLoopCounter) {
    // increment backedge counter for backward branches
    // rax: MDO
    // rbx: MDO bumped taken-count
    // rcx: method
    // rdx: target offset
    // r13: target bcp
    // r14: locals pointer
    __ testl(rdx, rdx);             // check if forward or backward branch
    __ jcc(Assembler::positive, dispatch); // count only if backward branch

    // check if MethodCounters exists
    Label has_counters;
    __ movptr(rax, Address(rcx, Method::method_counters_offset()));
    __ testptr(rax, rax);
    __ jcc(Assembler::notZero, has_counters);
    __ push(rdx);
    __ push(rcx);
    __ call_VM(noreg, CAST_FROM_FN_PTR(address, InterpreterRuntime::build_method_counters),
               rcx);
    __ pop(rcx);
    __ pop(rdx);
    __ movptr(rax, Address(rcx, Method::method_counters_offset()));
    __ testptr(rax, rax);
    __ jcc(Assembler::zero, dispatch);
    __ bind(has_counters);

    Label no_mdo;
    int increment = InvocationCounter::count_increment;
    if (ProfileInterpreter) {
      // Are we profiling?
      __ movptr(rbx, Address(rcx, in_bytes(Method::method_data_offset())));
      __ testptr(rbx, rbx);
      __ jccb(Assembler::zero, no_mdo);
      // Increment the MDO backedge counter
      const Address mdo_backedge_counter(rbx, in_bytes(MethodData::backedge_counter_offset()) +
          in_bytes(InvocationCounter::counter_offset()));
      const Address mask(rbx, in_bytes(MethodData::backedge_mask_offset()));
      __ increment_mask_and_jump(mdo_backedge_counter, increment, mask, rax, false, Assembler::zero,
          UseOnStackReplacement ? &backedge_counter_overflow : NULL);
      __ jmp(dispatch);
    }
    __ bind(no_mdo);
    // Increment backedge counter in MethodCounters*
    __ movptr(rcx, Address(rcx, Method::method_counters_offset()));
    const Address mask(rcx, in_bytes(MethodCounters::backedge_mask_offset()));
    __ increment_mask_and_jump(Address(rcx, be_offset), increment, mask,
        rax, false, Assembler::zero, UseOnStackReplacement ? &backedge_counter_overflow : NULL);
    __ bind(dispatch);
  }

  // Pre-load the next target bytecode into rbx
  __ load_unsigned_byte(rbx, Address(rbcp, 0));

  // continue with the bytecode @ target
  // rax: return bci for jsr's, unused otherwise
  // rbx: target bytecode
  // r13: target bcp
  __ dispatch_only(vtos, true);
```

invocation counter overflow if enable loop counter and OSR

```
  if (UseLoopCounter) {
    if (UseOnStackReplacement) {
      Label set_mdp;
      // invocation counter overflow
      __ bind(backedge_counter_overflow);
      __ negptr(rdx);
      __ addptr(rdx, rbcp); // branch bcp
      // IcoResult frequency_counter_overflow([JavaThread*], address branch_bcp)
      __ call_VM(noreg,
                 CAST_FROM_FN_PTR(address,
                                  InterpreterRuntime::frequency_counter_overflow),
                 rdx);

      // rax: osr nmethod (osr ok) or NULL (osr not possible)
      // rdx: scratch
      // r14: locals pointer
      // r13: bcp
      __ testptr(rax, rax);                        // test result
      __ jcc(Assembler::zero, dispatch);         // no osr if null
      // nmethod may have been invalidated (VM may block upon call_VM return)
      __ cmpb(Address(rax, nmethod::state_offset()), nmethod::in_use);
      __ jcc(Assembler::notEqual, dispatch);
```

We have the address of an on stack replacement routine in rax.
In preparation of invoking it, first we must migrate the locals and monitors from off the interpreter frame on the stack.
Ensure to save the osr nmethod over the migration call, it will be preserved in rbx.

```cpp
      __ mov(rbx, rax);

      NOT_LP64(__ get_thread(rcx));

      call_VM(noreg, CAST_FROM_FN_PTR(address, SharedRuntime::OSR_migration_begin));

      // rax is OSR buffer, move it to expected parameter location
      LP64_ONLY(__ mov(j_rarg0, rax));
      NOT_LP64(__ mov(rcx, rax));
      // We use j_rarg definitions here so that registers don't conflict as parameter
      // registers change across platforms as we are in the midst of a calling
      // sequence to the OSR nmethod and we don't want collision. These are NOT parameters.

      const Register retaddr   = LP64_ONLY(j_rarg2) NOT_LP64(rdi);
      const Register sender_sp = LP64_ONLY(j_rarg1) NOT_LP64(rdx);

      // pop the interpreter frame
      __ movptr(sender_sp, Address(rbp, frame::interpreter_frame_sender_sp_offset * wordSize)); // get sender sp
      __ leave();                                // remove frame anchor
      __ pop(retaddr);                           // get return address
      __ mov(rsp, sender_sp);                   // set sp to sender sp
      // Ensure compiled code always sees stack at proper alignment
      __ andptr(rsp, -(StackAlignmentInBytes));

      // unlike x86 we need no specialized return from compiled code
      // to the interpreter or the call stub.

      // push the return address
      __ push(retaddr);
```

begin the OSR nmethod

```cpp
      __ jmp(Address(rbx, nmethod::osr_entry_point_offset()));
    }
  }
}
```

### return

```cpp
// cpu/x86/templateInterpreterGenerator_x86.cpp
void TemplateTable::_return(TosState state) {
  transition(state, state);

  assert(_desc->calls_vm(),
         "inconsistent calls_vm information"); // call in remove_activation
```

register finalizer if override [Object.finalize()](/docs/CS/Java/JDK/Basic/Object.md?id=finalize)

```cpp
  if (_desc->bytecode() == Bytecodes::_return_register_finalizer) {
    assert(state == vtos, "only valid state");
    Register robj = LP64_ONLY(c_rarg1) NOT_LP64(rax);
    __ movptr(robj, aaddress(0));
    Register tmp_load_klass = LP64_ONLY(rscratch1) NOT_LP64(noreg);
    __ load_klass(rdi, robj, tmp_load_klass);
    __ movl(rdi, Address(rdi, Klass::access_flags_offset()));
    __ testl(rdi, JVM_ACC_HAS_FINALIZER);
    Label skip_register_finalizer;
    __ jcc(Assembler::zero, skip_register_finalizer);

    __ call_VM(noreg, CAST_FROM_FN_PTR(address, InterpreterRuntime::register_finalizer), robj);

    __ bind(skip_register_finalizer);
  }

  if (_desc->bytecode() != Bytecodes::_return_register_finalizer) {
```

check [InterpreterRuntime::at_safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md?id=at_safepoint) if need goto [SafePoint](/docs/CS/Java/JDK/JVM/Safepoint.md)

```cpp
    Label no_safepoint;
    NOT_PRODUCT(__ block_comment("Thread-local Safepoint poll"));
#ifdef _LP64
    __ testb(Address(r15_thread, JavaThread::polling_word_offset()), SafepointMechanism::poll_bit());
#else
    const Register thread = rdi;
    __ get_thread(thread);
    __ testb(Address(thread, JavaThread::polling_word_offset()), SafepointMechanism::poll_bit());
#endif
    __ jcc(Assembler::zero, no_safepoint);
    __ push(state);
    __ call_VM(noreg, CAST_FROM_FN_PTR(address,
                                       InterpreterRuntime::at_safepoint));
    __ pop(state);
    __ bind(no_safepoint);
  }

  // Narrow result if state is itos but result type is smaller.
  // Need to narrow in the return bytecode rather than in generate_return_entry
  // since compiled code callers expect the result to already be narrowed.
  if (state == itos) {
    __ narrow(rax);
  }
  __ remove_activation(state, rbcp);

  __ jmp(rbcp);
}
```

### putfield

```cpp

void TemplateTable::putfield_or_static(int byte_no, bool is_static, RewriteControl rc) {
  transition(vtos, vtos);

  const Register cache = rcx;
  const Register index = rdx;
  const Register obj   = rcx;
  const Register off   = rbx;
  const Register flags = rax;

  resolve_cache_and_index(byte_no, cache, index, sizeof(u2));
  jvmti_post_field_mod(cache, index, is_static);
  load_field_cp_cache_entry(obj, cache, index, off, flags, is_static);

  // [jk] not needed currently
  // volatile_barrier(Assembler::Membar_mask_bits(Assembler::LoadStore |
  //                                              Assembler::StoreStore));

  Label notVolatile, Done;
  __ movl(rdx, flags);
  __ shrl(rdx, ConstantPoolCacheEntry::is_volatile_shift);
  __ andl(rdx, 0x1);
```

Check for volatile store

```
  __ testl(rdx, rdx);
  __ jcc(Assembler::zero, notVolatile);

  putfield_or_static_helper(byte_no, is_static, rc, obj, off, flags);
  volatile_barrier(Assembler::Membar_mask_bits(Assembler::StoreLoad |
                                               Assembler::StoreStore));
  __ jmp(Done);
```

notVolatile

```
  __ bind(notVolatile);
  putfield_or_static_helper(byte_no, is_static, rc, obj, off, flags);

  __ bind(Done);
}
```

putfield_or_static_helper

```cpp
void TemplateTable::putfield_or_static_helper(int byte_no, bool is_static, RewriteControl rc,
                                              Register obj, Register off, Register flags) {

  // field addresses
  const Address field(obj, off, Address::times_1, 0*wordSize);
  NOT_LP64( const Address hi(obj, off, Address::times_1, 1*wordSize);)

  Label notByte, notBool, notInt, notShort, notChar,
        notLong, notFloat, notObj;
  Label Done;

  const Register bc    = LP64_ONLY(c_rarg3) NOT_LP64(rcx);

  __ shrl(flags, ConstantPoolCacheEntry::tos_state_shift);

  assert(btos == 0, "change code, btos != 0");
  __ andl(flags, ConstantPoolCacheEntry::tos_state_mask);
  __ jcc(Assembler::notZero, notByte);

  // btos
  {
    __ pop(btos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_BYTE, IN_HEAP, field, rax, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_bputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notByte);
  __ cmpl(flags, ztos);
  __ jcc(Assembler::notEqual, notBool);

  // ztos
  {
    __ pop(ztos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_BOOLEAN, IN_HEAP, field, rax, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_zputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notBool);
  __ cmpl(flags, atos);
  __ jcc(Assembler::notEqual, notObj);

  // atos
  {
    __ pop(atos);
    if (!is_static) pop_and_check_object(obj);
    // Store into the field
    do_oop_store(_masm, field, rax);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_aputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notObj);
  __ cmpl(flags, itos);
  __ jcc(Assembler::notEqual, notInt);

  // itos
  {
    __ pop(itos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_INT, IN_HEAP, field, rax, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_iputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notInt);
  __ cmpl(flags, ctos);
  __ jcc(Assembler::notEqual, notChar);

  // ctos
  {
    __ pop(ctos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_CHAR, IN_HEAP, field, rax, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_cputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notChar);
  __ cmpl(flags, stos);
  __ jcc(Assembler::notEqual, notShort);

  // stos
  {
    __ pop(stos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_SHORT, IN_HEAP, field, rax, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_sputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notShort);
  __ cmpl(flags, ltos);
  __ jcc(Assembler::notEqual, notLong);

  // ltos
  {
    __ pop(ltos);
    if (!is_static) pop_and_check_object(obj);
    // MO_RELAXED: generate atomic store for the case of volatile field (important for x86_32)
    __ access_store_at(T_LONG, IN_HEAP | MO_RELAXED, field, noreg /* ltos*/, noreg, noreg);
#ifdef _LP64
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_lputfield, bc, rbx, true, byte_no);
    }
#endif // _LP64
    __ jmp(Done);
  }

  __ bind(notLong);
  __ cmpl(flags, ftos);
  __ jcc(Assembler::notEqual, notFloat);

  // ftos
  {
    __ pop(ftos);
    if (!is_static) pop_and_check_object(obj);
    __ access_store_at(T_FLOAT, IN_HEAP, field, noreg /* ftos */, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_fputfield, bc, rbx, true, byte_no);
    }
    __ jmp(Done);
  }

  __ bind(notFloat);
#ifdef ASSERT
  Label notDouble;
  __ cmpl(flags, dtos);
  __ jcc(Assembler::notEqual, notDouble);
#endif

  // dtos
  {
    __ pop(dtos);
    if (!is_static) pop_and_check_object(obj);
    // MO_RELAXED: for the case of volatile field, in fact it adds no extra work for the underlying implementation
    __ access_store_at(T_DOUBLE, IN_HEAP | MO_RELAXED, field, noreg /* dtos */, noreg, noreg);
    if (!is_static && rc == may_rewrite) {
      patch_bytecode(Bytecodes::_fast_dputfield, bc, rbx, true, byte_no);
    }
  }

#ifdef ASSERT
  __ jmp(Done);

  __ bind(notDouble);
  __ stop("Bad state");
#endif

  __ bind(Done);
}
```

#### volatile_barrier

Volatile variables demand their effects be made known to all CPU's
in order.
Store buffers on most chips allow reads & writes to reorder;
the JMM's ReadAfterWrite.java test fails in -Xint mode
without some kind of memory barrier (i.e., it's not sufficient that
the interpreter does not reorder volatile references, the hardware
also must not reorder them).

According to the new Java Memory Model (JMM):

1. All volatiles are serialized wrt to each other.  ALSO reads &
   writes act as aquire & release, so:
2. A read cannot let unrelated NON-volatile memory refs that
   happen after the read float up to before the read.  It's OK for
   non-volatile memory refs that happen before the volatile read to
   float down below it.
3. Similar a volatile write cannot let unrelated NON-volatile
   memory refs that happen BEFORE the write float down to after the
   write.  It's OK for non-volatile memory refs that happen after the
   volatile write to float up before it.

We only put in barriers around volatile refs (they are expensive),
not _between_ memory refs (that would require us to track the
flavor of the previous memory refs).  Requirements 2 and 3
require some barriers before volatile stores and after volatile
loads.  These nearly cover requirement 1 but miss the
volatile-store-volatile-load case.
This final case is placed after
volatile-stores although it could just as well go before
volatile-loads.

```cpp
// 
void TemplateTable::volatile_barrier(Assembler::Membar_mask_bits order_constraint ) {
  // Helper function to insert a is-volatile test and memory barrier
  __ membar(order_constraint);
}

```

We only have to handle **StoreLoad**

All usable chips support "locked" instructions which suffice
as barriers, and are much faster than the alternative of
using cpuid instruction. We use here a locked add [esp-C],0.
This is conveniently otherwise a no-op except for blowing
flags, and introducing a false dependency on target memory
location. We can't do anything with flags, but we can avoid
memory dependencies in the current method by locked-adding
somewhere else on the stack. Doing [esp+C] will collide with
something on stack in current method, hence we go for [esp-C].
It is convenient since it is almost always in data cache, for
any small C.  We need to step back from SP to avoid data
dependencies with other things on below SP (callee-saves, for
example). Without a clear way to figure out the minimal safe
distance from SP, it makes sense to step back the complete
cache line, as this will also avoid possible second-order effects
with locked ops against the cache line.
Our choice of offset is bounded by x86 operand encoding, which should stay within [-128; +127] to have the 8-byte displacement encoding.

Any change to this code may need to revisit other places in
the code where this idiom is used, in particular the
orderAccess code.

```
void Assembler::membar(Membar_mask_bits order_constraint) {
  if (order_constraint & StoreLoad) {
    int offset = -VM_Version::L1_line_size();
    if (offset < -128) {
      offset = -128;
    }

```

Do you remember `lock addl` in [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)?

```cpp
    lock();
    addl(Address(rsp, offset), 0);// Assert the lock# signal here
  }
}
```

## CppInterpreter

BytecodeInterpreter

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
