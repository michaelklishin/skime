import re
import yaml

def gen_tags(tags):
    stmts =  []
    for tag, i in zip(tags, range(len(tags))):
        stmts.append('TAG_%-12s = %d' % (tag.upper(), 2**i))
    return '\n'.join(stmts)

def gen_actions(instructions):
    def gen_action(insn):
        func = "def op_%s(ctx):\n" % insn['name']

        env = {
            'insn_len' : 1 + len(insn['operands'])
            }
        code = insn['code']
        if not 'ctrl_flow' in insn['tags']:
            code += 'ctx.ip += $(insn_len)\n'
            
        code = process_tmpl(code, env)
        code = re.sub(re.compile('^', re.MULTILINE), '    ', code)
        
        return func + code

    return '\n'.join([gen_action(insn)
                      for insn in instructions])

def gen_action_table(instructions):
    return 'INSN_ACTION = [\n' + \
           ',\n'.join(['    op_' + insn['name']
                       for insn in instructions]) + \
           '\n]\n'


def gen_tags_table(instructions):
    def gen_tag(insn):
        if len(insn['tags']) == 0:
            return '0'
        else:
            return ' | '.join(['TAG_%s' % tag.upper()
                               for tag in insn['tags']])

    return 'INSN_TAGS = [\n' + \
           ',\n'.join(['    ' + gen_tag(insn)
                       for insn in instructions]) + \
           '\n]\n'

def gen_insn_table(instructions):
    def gen_insn(i, insn):
        return "Instruction(" + str(i) + ",\n" + \
               ",\n".join(["            " + insn[key].__repr__()
                           for key in ['name', 'tags', 'desc', 'operands',
                                       'stack_before', 'stack_after', 'code']]) + \
               ")"

    insns = zip(range(len(instructions)), instructions)
    
    return "INSTRUCTIONS = [\n" + \
           ",\n".join([gen_insn(i, insn)
                      for i, insn in insns]) + \
           "]\n\nINSN_MAP = {\n" + \
           ",\n".join(['    ' + insn['name'].__repr__() + ' : INSTRUCTIONS[%d]' % i
                       for i, insn in insns]) + \
           "\n}\n"
    

def process_tmpl(tmpl, env):
    """\
    Process template. Special variables like $(key) in the template
    will be replaced by the value found in env (env['key']).
    """
    PATTERN = re.compile(r"\$\(([^)]+)\)")
    return re.sub(PATTERN, lambda m: str(env[m.group(1)]), tmpl)
    
    
TMPL_INSNS = """\
# Don't edit this file. This is generated by iset_gen.py

from .ctx        import Context
from .proc       import Procedure
from .prim       import Primitive
from .types.pair import Pair
from .errors     import WrongArgType

$(tags)

$(actions)

$(action_table)

$(tags_table)


def has_tag(opcode, tag):
    return INSN_TAGS[opcode] & tag == tag

def get_param(ctx, n):
    return ctx.bytecode[ctx.ip+n]

def run(vm):
    ctx = vm.ctx
    while ctx.ip < len(ctx.bytecode):
        opcode = ctx.bytecode[ctx.ip]
        INSN_ACTION[opcode](ctx)
        if has_tag(opcode, TAG_CTX_SWITCH):
            ctx = vm.ctx
"""

TMPL_ISET = """\
# Don't edit this file. This is generated by iset_gen.py

class Instruction(object):
    __slots__ = ('opcode',
                 'name',
                 'tags',
                 'desc',
                 'operands',
                 'stack_before',
                 'stack_after',
                 'code')
    def __init__(self, opcode, name, tags, desc, operands,
                 stack_before, stack_after, code):
        self.opcode = opcode
        self.name = name
        self.tags = tags
        self.desc = desc
        self.operands = operands
        self.stack_before = stack_before
        self.stack_after = stack_after
        self.code = code

    def length_get(self):
        return len(self.operands)+1
    def length_set(self):
        raise AttributeError, 'length attribute is read only'
    length = property(length_get, length_set, 'length of the instruction')

$(instruction_table)
"""

if __name__ == '__main__':
    iset = yaml.load(open("iset.yml").read())

    env = {
        'tags' : gen_tags(iset['tags']),
        'actions' : gen_actions(iset['instructions']),
        'instruction_table' : gen_insn_table(iset['instructions']),
        'action_table' : gen_action_table(iset['instructions']),
        'tags_table' : gen_tags_table(iset['instructions'])
        }

    py = open("iset.py", "w")
    py.write(process_tmpl(TMPL_ISET, env))
    py.close()

    py = open("insns.py", "w")
    py.write(process_tmpl(TMPL_INSNS, env))
    py.close()
