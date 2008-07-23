from types          import NoneType
                      
from ..types.symbol import Symbol as sym
from ..types.pair   import Pair as pair
from ..macro        import Macro
                     
from ..errors       import CompileError
from ..errors       import SyntaxError

from .builder       import Builder

class Compiler(object):
    """\
    The compiler for skime. It compiles sexp to bytecode.
    """

    sym_begin = sym("begin")
    sym_define = sym("define")
    sym_set_x = sym("set!")
    sym_if = sym("if")
    sym_lambda = sym("lambda")
    sym_quote = sym("quote")
    sym_or = sym("or")
    sym_and = sym("and")
    sym_define_syntax = sym("define-syntax")
    sym_syntax_rules = sym("syntax-rules")
    
    def __init__(self):
        self.label_seed = 0

    def compile(self, sexp, env):
        bdr = Builder(env)

        self.generate_expr(bdr, sexp, keep=True, tail=False)

        form = bdr.generate()
        return form

    ########################################
    # Helper functions
    ########################################
    def get_macro(self, env, name):
        if not isinstance(name, sym):
            return None
        loc = env.lookup_location(name.name)
        val = loc.env.read_local(loc.idx)
        if isinstance(val, Macro):
            return val
        return None
    
    def self_evaluating(self, expr):
        for t in [int, long, complex, float, str, unicode, bool, NoneType]:
            if isinstance(expr, t):
                return True
        return False
        
    def next_label(self):
        self.label_seed += 1
        return "__lbl_%d" % self.label_seed

    def generate_body(self, bdr, body, keep=True, tail=False):
        "Generate a sequence of sexps."
        if body is None and keep:
            bdr.emit("push_nil")
            if tail:
                bdr.emit("ret")

        while body is not None:
            expr = body.first
            body = body.rest
            will_keep = keep and body is None
            self.generate_expr(bdr, expr, keep=will_keep, tail=will_keep and tail)

    def generate_expr(self, bdr, expr, keep=True, tail=False):
        """\
        Generate instructions for an expression.

        if keep == True, the value of the expression is kept on
        the stack, otherwise, it is popped or never pushed.

        if tail == True, a tail call or ret will be emitted. tail
        can never be true if keep is False.
        """
        mapping = {
            Compiler.sym_if: self.generate_if_expr,
            Compiler.sym_begin: self.generate_body,
            Compiler.sym_lambda: self.generate_lambda,
            Compiler.sym_define: self.generate_define,
            Compiler.sym_set_x: self.generate_set_x,
            Compiler.sym_quote: self.generate_quote,
            Compiler.sym_or: self.generate_or,
            Compiler.sym_and: self.generate_and,
            Compiler.sym_define_syntax: self.generate_define_syntax
            }
        if self.self_evaluating(expr):
            if keep:
                bdr.emit('push_literal', expr)
                if tail:
                    bdr.emit('ret')
        
        elif isinstance(expr, sym):
            if keep:
                bdr.emit_local("push", expr.name)
                if tail:
                    bdr.emit('ret')

        elif isinstance(expr, pair):
            routine = mapping.get(expr.first)
            if routine is not None:
                routine(bdr, expr.rest, keep=keep, tail=tail)
            else:
                macro = self.get_macro(bdr.env, expr.first)
                while macro is not None:
                    expr = macro.transform(bdr.env, expr)
                    if not isinstance(expr, pair):
                        return self.generate_expr(bdr, expr, keep=keep, tail=tail)
                    macro = self.get_macro(bdr.env, expr.first)
                
                argc = 0
                arg  = expr.rest
                while arg is not None:
                    self.generate_expr(bdr, arg.first, keep=True, tail=False)
                    arg = arg.rest
                    argc += 1
                self.generate_expr(bdr, expr.first, keep=True, tail=False)
                if tail:
                    bdr.emit('tail_call', argc)
                else:
                    bdr.emit('call', argc)
                    if not keep:
                        bdr.emit('pop')

        else:
            raise CompileError("Expecting atom or list, but got %s" % expr)

    def generate_if_expr(self, bdr, expr, keep=True, tail=False):
        if expr is None:
            raise SyntaxError("Missing condition expression in 'if'")
            
        cond = expr.first
        expthen = expr.rest
        if expthen is None:
            raise SyntaxError("Missing 'then' expression in 'if'")
        expthen = expthen.first

        expelse = expr.rest.rest
        if expelse is not None:
            if expelse.rest is not None:
                raise SyntaxError("Extra expression in 'if'")
            expelse = expelse.first

        self.generate_expr(bdr, cond, keep=True, tail=False)

        if keep is True:
            lbl_then = self.next_label()
            lbl_end = self.next_label()
            bdr.emit('goto_if_not_false', lbl_then)
            if expelse is None:
                bdr.emit('push_nil')
                if tail:
                    bdr.emit('ret')
            else:
                self.generate_expr(bdr, expelse, keep=True, tail=tail)
            if not tail:
                bdr.emit('goto', lbl_end)
            bdr.def_label(lbl_then)
            self.generate_expr(bdr, expthen, keep=True, tail=tail)
            bdr.def_label(lbl_end)
        else:
            if expelse is None:
                lbl_end = self.next_label()
                bdr.emit('goto_if_false', lbl_end)
                self.generate_expr(bdr, expthen, keep=False, tail=False)
                bdr.def_label(lbl_end)
            else:
                lbl_then = self.next_label()
                lbl_end = self.next_label()
                bdr.emit('goto_if_not_false', lbl_then)
                self.generate_expr(bdr, expelse, keep=False, tail=False)
                bdr.emit('goto', lbl_end)
                bdr.def_label(lbl_then)
                self.generate_expr(bdr, expthen, keep=False, tail=False)
                bdr.def_label(lbl_end)

    def generate_lambda(self, base_builder, expr, keep=True, tail=False):
        if keep is not True:
            return  # lambda expression has no side-effect
        try:
            arglst = expr.first
            body = expr.rest

            if isinstance(arglst, pair):
                args = []
                while isinstance(arglst, pair):
                    args.append(arglst.first.name)
                    arglst = arglst.rest
                if arglst is None:
                    rest_arg = False
                else:
                    args.append(arglst.name)
                    rest_arg = True
            elif arglst is None:
                rest_arg = False
                args = []
            else:
                rest_arg = True
                args = [arglst.name]

            bdr = base_builder.push_proc(args=args, rest_arg=rest_arg)
            self.generate_body(bdr, body, keep=True, tail=True)
            base_builder.emit("make_lambda")
            
            if tail:
                base_builder.emit('ret')

        except AttributeError, e:
            raise SyntaxError("Broken lambda expression: "+e.message)
        
    def generate_define(self, bdr, expr, keep=True, tail=False):
        if expr is None:
            raise SyntaxError("Empty define expression")
        var = expr.first
        
        if isinstance(var, pair):
            gen = self.generate_lambda
            val = pair(var.rest, expr.rest)
            var = var.first
        elif isinstance(var, sym):
            gen = self.generate_expr
            val = expr.rest
            if val is None:
                raise SyntaxError("Missing value for defined variable")
            if val.rest is not None:
                raise SyntaxError("Extra expressions in 'define'")
            val = val.first
        else:
            raise SyntaxError("Invalid define expression")

        # first define local, then generate value. This allow
        # recursive function to be compiled properly.
        bdr.def_local(var.name)
        gen(bdr, val, keep=True, tail=False)
        if keep is True:
            bdr.emit('dup')
        bdr.emit_local('set', var.name)
        if tail:
            bdr.emit('ret')

    def generate_set_x(self, bdr, expr, keep=True, tail=False):
        if expr is None:
            raise SyntaxError("Empty set! expression")
        var = expr.first

        if not isinstance(var, sym):
            raise SyntaxError("Invalid set! expression, expecting symbol")
        val = expr.rest

        if val is None:
            raise SyntaxError("Missing value for set! expression")
        if val.rest is not None:
            raise SyntaxError("Extra expressions in 'set!'")
        val = val.first

        self.generate_expr(bdr, val, keep=True, tail=False)
        if keep:
            bdr.emit('dup')
        bdr.emit_local('set', var.name)
        if tail:
            bdr.emit('ret')

    def generate_quote(self, bdr, expr, keep=True, tail=False):
        if keep:
            bdr.emit('push_literal', expr.first)
            if tail:
                bdr.emit('ret')

    def generate_or(self, bdr, expr, keep=True, tail=False):
        lbl_end = self.next_label()
        expr_generated = False
        while isinstance(expr, pair):
            el = expr.first
            expr = expr.rest
            # 'False' literal in 'or' expression can be silently
            # ignored
            if el is not False:
                expr_generated = True
                self.generate_expr(bdr, el, keep=True, tail=False)
                if keep:
                    bdr.emit('dup')
                bdr.emit('goto_if_not_false', lbl_end)
                if keep:
                    if expr is not None:
                        bdr.emit('pop')
        if expr is not None:
            raise SyntaxError("Invalid element in or expression: %s" % expr)
        if keep:
            if not expr_generated:
                bdr.emit('push_false')
            if tail:
                bdr.emit('ret')
                
        bdr.def_label(lbl_end)

    def generate_and(self, bdr, expr, keep=True, tail=False):
        lbl_end = self.next_label()
        expr_generated = False
        while isinstance(expr, pair):
            el = expr.first
            expr = expr.rest
            # 'True' literal in 'and' expression can be silently
            # ignored
            if el is not True:
                expr_generated = True
                self.generate_expr(bdr, el, keep=True, tail=False)
                if keep:
                    bdr.emit('dup')
                bdr.emit('goto_if_false', lbl_end)
                if keep:
                    if expr is not None:
                        bdr.emit('pop')
        if expr is not None:
            raise SyntaxError("Invalid element in or expression: %s" % expr)
        if keep:
            if not expr_generated:
                bdr.emit('push_true')
            if tail:
                bdr.emit('ret')
                
        bdr.def_label(lbl_end)

    def generate_define_syntax(self, bdr, expr, keep=True, tail=False):
        if not isinstance(expr, pair):
            raise SyntaxError("Invalid define-syntax expression, expecting macro keyword")
        name = expr.first
        if not isinstance(name, sym):
            raise SyntaxError("Expecting macro keyword as a symbol, but got %s" % name)
        expr = expr.rest
        if not isinstance(expr, pair) or \
               not isinstance(expr.first, pair) or \
               Compiler.sym_syntax_rules != expr.first.first:
            raise SyntaxError("Expecting syntax-rules, but got %s" % expr.first)
        if expr.rest is not None:
            raise SyntaxError("Extra expressions in define-syntax: %s" % expr.rest)
        
        # define local before constructing the macro, so that recursive macro
        # can be supported
        idx = bdr.def_local(name.name)
        macro = Macro(bdr.env, expr.first.rest)
        bdr.env.assign_local(idx, macro)

        if keep:
            # macro object is generally not available at runtime, the value of
            # 'define-syntax' expression is None
            bdr.emit('push_nil')
            if tail:
                bdr.emit('ret')
