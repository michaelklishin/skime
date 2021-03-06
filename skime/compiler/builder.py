from array    import array

from ..iset   import INSN_MAP
from ..form   import Form
from ..proc   import Procedure
from ..env    import Environment
from ..errors import UnboundVariable

class Builder(object):
    "Builder is a helper of building the bytecode for a form."
    def __init__(self, env, result_t=Form):
        # The lexical scope where the form is compiled
        self.env = env
        # The type of the generate result
        # By default it is a Form class
        self.result_t = result_t

        # Instructions stream
        self.stream = []
        # Program counter (instruction pointer)
        self.ip = 0
        # Maps label names to instruction pointers
        self.labels = {}
        # Literals list
        self.literals = []

    def emit(self, insn_name, *args):
        """
        Emits an instruction.

        Instructions emitted by the builder and appended
        to the instructions stream with it's arguments
        as a single tuple of 2: (instruction, arguments tuple).
        """
        # Get instruction by name
        # from generated instructions map that looks
        # like this:
        #
        # 'ret' : INSTRUCTIONS[0],
        # 'call' : INSTRUCTIONS[1],
        # 'tail_call' : INSTRUCTIONS[2],
        # 'call_cc' : INSTRUCTIONS[3],
        # 'pop' : INSTRUCTIONS[4]
        #
        # See generated iset.py, iset.yml
        # and iset_gen.py.
        insn = INSN_MAP.get(insn_name)
        # unknown instruction, should never happen
        if insn is None:
            raise TypeError, "No such instruction: %s" % insn_name
        # check number of given arguments
        # it always must be instruction name plus
        # instructions arguments count
        #
        # if it isn't so, raise
        if insn.length != 1+len(args):
            raise TypeError, \
                  "INSTRUCTION %s expects %d parameters, but %d given" % \
                  (insn_name, insn.length-1, len(args))

        # pick more specific push_* instruction
        # based on argument type
        if insn_name == 'push_literal':
            lit = args[0]
            # True == 1, False == 0 in Python, so "is True/False"
            # test should be put before "== 0/1" test.
            if lit is True:
                insn_name = 'push_true'
                args = ()
            elif lit is False:
                insn_name = 'push_false'
                args = ()
            elif lit == 0 and isinstance(lit, int):
                insn_name = 'push_0'
                args = ()
            elif lit == 1 and isinstance(lit, int):
                insn_name = 'push_1'
                args = ()
            elif lit is None:
                insn_name = 'push_nil'
                args = ()

        # append emitted instruction to the stream
        self.stream.append((insn_name, args))
        # increment instruction pointer
        self.ip += len(args)+1

    def def_local(self, name):
        "Define a local variable."
        return self.env.alloc_local(name)

    def def_label(self, name):
        "Define a label at current ip."
        if self.labels.get(name) is not None:
            raise TypeError, "Duplicated label: %s" % name
        self.labels[name] = self.ip

    def emit_local(self, action, name, dyn_env=None):
        """\
        Emit an instruction to push or set local variable. The local variable
        is automatically searched in the current context and parents.

        This function causes execution of another instruction
        with dynamically generated name.
        """
        if dyn_env is None:
            env = self.env
            dyn = ""
        else:
            env = dyn_env
            dyn = "dynamic_"

        # get nesting and index of local variable
        depth, idx = self.find_local_depth(name, env)
        # no nesting means variable is undefined
        if depth is None:
            raise UnboundVariable(name, "Unbound variable %s" % name)
        if depth == 0:
            postfix = ''
            args = (idx,)
        else:
            postfix = '_depth'
            args = (depth, idx)
        self.emit('%s%s_local%s' % (dyn, action, postfix), *args)

    def push_proc(self, args=[], rest_arg=False, parent_env=None):
        """\
        Return a builder for building a procedure. The returned builder
        is used to build the body of the procedure.

        Later when self.generate is called, builder.generate will be called
        automatically to get the procedure object, add it to the literals
        and push to the operand stack.
        """
        if parent_env is None:
            parent_env = self.env
        # create a new environment for procedure
        env = Environment(parent_env)
        # Define procedure arguments as local variables
        for x in args:
            env.alloc_local(x)

        bdr = Builder(env, result_t=Procedure)
        # Those properties are recorded in the builder and used
        # to construct the procedure later
        bdr.args = args
        bdr.rest_arg = rest_arg

        # generate_proc is a pseudo instruction
        self.stream.append(('generate_proc', bdr))
        self.ip += 3 # push_literal + fix_lexical (2+1)
        
        return bdr

    def generate(self):
        """\
        Generate a form with emitted instructions.

        Real instruction results in an optcode followed
        by instruction arguments. Arguments vary depending
        on instruction type but not much. There are 3
        different cases:

        1. goto* instructions that need a position argument
        2. push_literal instruction needs a literal index in literals list
        3. the rest of instructions needs list of arguments "as given"

        since bytecode is a stream of integers, labels used by goto*
        are replaced by actual ip positions.

        This function returns an instance of Form or Procedure but
        may return any other object that has attached bytecode.
        """
        # bc is for bytecodes
        bc = array('i')
        for insn_name, args in self.stream:
            # pseudo instructions
            if insn_name == 'generate_proc':
                idx = len(self.literals)
                self.literals.append(args.generate())
                bc.append(INSN_MAP['push_literal'].opcode)
                bc.append(idx)
            # real instructions
            else:
                insn = INSN_MAP[insn_name]
                bc.append(insn.opcode)
                
                if insn_name in ['goto', 'goto_if_false', 'goto_if_not_false']:
                    bc.append(self.labels[args[0]])
                elif insn_name == 'push_literal':
                    bc.append(self.get_literal_idx(args[0]))
                else:
                    for x in args:
                        bc.append(x)

        return self.result_t(self, bc)

        
    ########################################
    # Helpers used internally
    ########################################
    def find_local_depth(self, name, env):
        """\
        Find the depth and index of a local variable. If no variable
        with the given name is found, return (None, None).
        """
        depth = 0
        while env is not None:
            idx = env.find_local(name)
            if idx is not None:
                return (depth, idx)
            depth += 1
            env = env.parent
        return (None, None)

    def get_literal_idx(self, lit):
        """\
        Return the index in literals list if there. Or else append
        the literal to the literals list.
        """
        for i in range(len(self.literals)):
            # make sure type is the same so that 42 and 42.0 will be
            # different literals
            l = self.literals[i]
            if type(l) is type(lit) and \
               l == lit:
                return i
        self.literals.append(lit)
        return len(self.literals)-1
