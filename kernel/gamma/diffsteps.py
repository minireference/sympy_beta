import sympy
import collections
from functools import reduce

from sympy.core.function import AppliedUndef
from sympy.functions.elementary.trigonometric import TrigonometricFunction
from sympy.strategies.core import switch

from .stepprinter import functionnames, replace_u_var, JSONPrinter


def Rule(name, props=""):
    return collections.namedtuple(name, props + " context symbol")


ConstantRule = Rule("ConstantRule", "number")
ConstantTimesRule = Rule("ConstantTimesRule", "constant other substep")
PowerRule = Rule("PowerRule", "base exp")
AddRule = Rule("AddRule", "substeps")
MulRule = Rule("MulRule", "terms substeps")
DivRule = Rule("DivRule", "numerator denominator numerstep denomstep")
ChainRule = Rule("ChainRule", "substep inner u_var innerstep")
TrigRule = Rule("TrigRule", "f")
ExpRule = Rule("ExpRule", "f base")
LogRule = Rule("LogRule", "arg base")
FunctionRule = Rule("FunctionRule")
AlternativeRule = Rule("AlternativeRule", "alternatives")
DontKnowRule = Rule("DontKnowRule")
RewriteRule = Rule("RewriteRule", "rewritten substep")

DerivativeInfo = collections.namedtuple('DerivativeInfo', 'expr symbol')

evaluators = {}
def evaluates(rule):
    def _evaluates(func):
        func.rule = rule
        evaluators[rule] = func
        return func
    return _evaluates

def power_rule(derivative):
    expr, symbol = derivative.expr, derivative.symbol
    base, exp = expr.as_base_exp()

    if not base.has(symbol):
        if isinstance(exp, sympy.Symbol):
            return ExpRule(expr, base, expr, symbol)
        else:
            u = sympy.Dummy()
            f = base ** u
            return ChainRule(
                ExpRule(f, base, f, u),
                exp, u,
                diff_steps(exp, symbol),
                expr, symbol
            )
    elif not exp.has(symbol):
        if isinstance(base, sympy.Symbol):
            return PowerRule(base, exp, expr, symbol)
        else:
            u = sympy.Dummy()
            f = u ** exp
            return ChainRule(
                PowerRule(u, exp, f, u),
                base, u,
                diff_steps(base, symbol),
                expr, symbol
            )
    else:
        return DontKnowRule(expr, symbol)

def add_rule(derivative):
    expr, symbol = derivative.expr, derivative.symbol
    return AddRule([diff_steps(arg, symbol) for arg in expr.args],
                   expr, symbol)

def constant_rule(derivative):
    expr, symbol = derivative.expr, derivative.symbol
    return ConstantRule(expr, expr, symbol)

def mul_rule(derivative):
    expr, symbol = derivative
    terms = expr.args

    coeff, f = expr.as_independent(symbol)

    if coeff != 1:
        return ConstantTimesRule(coeff, f, diff_steps(f, symbol), expr, symbol)

    numerator, denominator = expr.as_numer_denom()
    if denominator != 1:
        return DivRule(numerator, denominator,
                       diff_steps(numerator, symbol),
                       diff_steps(denominator, symbol), expr, symbol)

    return MulRule(terms, [diff_steps(g, symbol) for g in terms], expr, symbol)

def trig_rule(derivative):
    expr, symbol = derivative
    arg = expr.args[0]

    default = TrigRule(expr, expr, symbol)
    if not isinstance(arg, sympy.Symbol):
        u = sympy.Dummy()
        default = ChainRule(
            TrigRule(expr.func(u), expr.func(u), u),
            arg, u, diff_steps(arg, symbol),
            expr, symbol)

    if isinstance(expr, (sympy.sin, sympy.cos)):
        return default
    elif isinstance(expr, sympy.tan):
        f_r = sympy.sin(arg) / sympy.cos(arg)

        return AlternativeRule([
            default,
            RewriteRule(f_r, diff_steps(f_r, symbol), expr, symbol)
        ], expr, symbol)
    elif isinstance(expr, sympy.csc):
        f_r = 1 / sympy.sin(arg)

        return AlternativeRule([
            default,
            RewriteRule(f_r, diff_steps(f_r, symbol), expr, symbol)
        ], expr, symbol)
    elif isinstance(expr, sympy.sec):
        f_r = 1 / sympy.cos(arg)

        return AlternativeRule([
            default,
            RewriteRule(f_r, diff_steps(f_r, symbol), expr, symbol)
        ], expr, symbol)
    elif isinstance(expr, sympy.cot):
        f_r_1 = 1 / sympy.tan(arg)
        f_r_2 = sympy.cos(arg) / sympy.sin(arg)
        return AlternativeRule([
            default,
            RewriteRule(f_r_1, diff_steps(f_r_1, symbol), expr, symbol),
            RewriteRule(f_r_2, diff_steps(f_r_2, symbol), expr, symbol)
        ], expr, symbol)


def exp_rule(derivative):
    expr, symbol = derivative
    exp = expr.args[0]
    if isinstance(exp, sympy.Symbol):
        return ExpRule(expr, sympy.E, expr, symbol)
    else:
        u = sympy.Dummy()
        f = sympy.exp(u)
        return ChainRule(ExpRule(f, sympy.E, f, u),
                         exp, u, diff_steps(exp, symbol), expr, symbol)

def log_rule(derivative):
    expr, symbol = derivative
    arg = expr.args[0]
    base = sympy.E
    if isinstance(arg, sympy.Symbol):
        return LogRule(arg, base, expr, symbol)
    else:
        u = sympy.Dummy()
        return ChainRule(LogRule(u, base, sympy.log(u, base), u), arg, u, diff_steps(arg, symbol), expr, symbol)

def function_rule(derivative):
    expr, symbol = derivative
    arg = expr.args[0]   # XXX: only works for unary function
    if isinstance(arg, sympy.Symbol):
        return FunctionRule(expr, symbol)
    else:
        u = sympy.Dummy()
        return ChainRule(FunctionRule(expr.func(u), u), arg, u, diff_steps(arg, symbol), expr, symbol)

@evaluates(ConstantRule)
def eval_constant(*args):
    return 0

@evaluates(ConstantTimesRule)
def eval_constanttimes(constant, other, substep, expr, symbol):
    return constant * diff(substep)

@evaluates(AddRule)
def eval_add(substeps, expr, symbol):
    results = [diff(step) for step in substeps]
    return sum(results)

@evaluates(DivRule)
def eval_div(numer, denom, numerstep, denomstep, expr, symbol):
    d_numer = diff(numerstep)
    d_denom = diff(denomstep)
    return (denom * d_numer - numer * d_denom) / (denom **2)

@evaluates(ChainRule)
def eval_chain(substep, inner, u_var, innerstep, expr, symbol):
    return diff(substep).subs(u_var, inner) * diff(innerstep)

@evaluates(PowerRule)
@evaluates(ExpRule)
@evaluates(LogRule)
@evaluates(DontKnowRule)
@evaluates(FunctionRule)
def eval_default(*args):
    func, symbol = args[-2], args[-1]

    if isinstance(func, sympy.Symbol):
        func = sympy.Pow(func, 1, evaluate=False)

    # Automatically derive and apply the rule (don't use diff() directly as
    # chain rule is a separate step)
    substitutions = []
    mapping = {}
    constant_symbol = sympy.Dummy()
    for arg in func.args:
        if symbol in arg.free_symbols:
            mapping[symbol] = arg
            substitutions.append(symbol)
        else:
            mapping[constant_symbol] = arg
            substitutions.append(constant_symbol)

    rule = func.func(*substitutions).diff(symbol)
    return rule.subs(mapping)

@evaluates(MulRule)
def eval_mul(terms, substeps, expr, symbol):
    diffs = list(map(diff, substeps))

    result = sympy.S.Zero
    for i in range(len(terms)):
        subresult = diffs[i]
        for index, term in enumerate(terms):
            if index != i:
                subresult *= term
        result += subresult
    return result

@evaluates(TrigRule)
def eval_default_trig(*args):
    return sympy.trigsimp(eval_default(*args))

@evaluates(RewriteRule)
def eval_rewrite(rewritten, substep, expr, symbol):
    return diff(substep)

@evaluates(AlternativeRule)
def eval_alternative(alternatives, expr, symbol):
    return diff(alternatives[1])

def diff_steps(expr, symbol):
    deriv = DerivativeInfo(expr, symbol)

    def key(deriv):
        expr = deriv.expr
        if isinstance(expr, TrigonometricFunction):
            return TrigonometricFunction
        elif isinstance(expr, AppliedUndef):
            return AppliedUndef
        elif not expr.has(symbol):
            return 'constant'
        else:
            return expr.func

    return switch(key, {
        sympy.Pow: power_rule,
        sympy.Symbol: power_rule,
        sympy.Dummy: power_rule,
        sympy.Add: add_rule,
        sympy.Mul: mul_rule,
        TrigonometricFunction: trig_rule,
        sympy.exp: exp_rule,
        sympy.log: log_rule,
        AppliedUndef: function_rule,
        'constant': constant_rule
    })(deriv)

def diff(rule):
    try:
        return evaluators[rule.__class__](*rule)
    except KeyError:
        raise ValueError("Cannot evaluate derivative")


class DiffPrinter(JSONPrinter):
    def print_rule(self, rule):
        if isinstance(rule, PowerRule):
            self.print_Power(rule)
        elif isinstance(rule, ChainRule):
            self.print_Chain(rule)
        elif isinstance(rule, ConstantRule):
            self.print_Number(rule)
        elif isinstance(rule, ConstantTimesRule):
            self.print_ConstantTimes(rule)
        elif isinstance(rule, AddRule):
            self.print_Add(rule)
        elif isinstance(rule, MulRule):
            self.print_Mul(rule)
        elif isinstance(rule, DivRule):
            self.print_Div(rule)
        elif isinstance(rule, TrigRule):
            self.print_Trig(rule)
        elif isinstance(rule, ExpRule):
            self.print_Exp(rule)
        elif isinstance(rule, LogRule):
            self.print_Log(rule)
        elif isinstance(rule, DontKnowRule):
            self.print_DontKnow(rule)
        elif isinstance(rule, AlternativeRule):
            self.print_Alternative(rule)
        elif isinstance(rule, RewriteRule):
            self.print_Rewrite(rule)
        elif isinstance(rule, FunctionRule):
            self.print_Function(rule)
        else:
            self.append(repr(rule))

    def print_Power(self, rule):
        with self.new_step():
            self.append(self.format_text("Apply the power rule: "),
                        self.format_math(rule.context),
                        self.format_text(" goes to "),
                        self.format_math(diff(rule)))

    def print_Number(self, rule):
        with self.new_step():
            self.append(self.format_text("The derivative of the constant "),
                        self.format_math(rule.number),
                        self.format_text(" is zero."))

    def print_ConstantTimes(self, rule):
        with self.new_step():
            self.append(self.format_text("The derivative of a constant times a function "
                                         "is the constant times the derivative of the function."))
            with self.new_level():
                self.print_rule(rule.substep)
            self.append(self.format_text("So, the result is: "),
                        self.format_math(diff(rule)))

    def print_Add(self, rule):
        with self.new_step():
            self.append(self.format_text("Differentiate "),
                        self.format_math(rule.context),
                        self.format_text(" term by term:"))
            with self.new_level():
                for substep in rule.substeps:
                    self.print_rule(substep)
            self.append(self.format_text("The result is: "),
                        self.format_math(diff(rule)))

    def print_Mul(self, rule):
        with self.new_step():
            self.append(self.format_text("Apply the product rule: "),
                        self.format_math(rule.context))

            fnames = [sympy.Function(n)(rule.symbol) for n in functionnames(len(rule.terms))]
            derivatives = [sympy.Derivative(f, rule.symbol) for f in fnames]
            ruleform = []
            for index in range(len(rule.terms)):
                buf = []
                for i in range(len(rule.terms)):
                    if i == index:
                        buf.append(derivatives[i])
                    else:
                        buf.append(fnames[i])
                ruleform.append(reduce(lambda a, b: a*b, buf))
            self.append(self.format_math_display(
                sympy.Eq(sympy.Derivative(reduce(lambda a, b: a*b, fnames), rule.symbol), sum(ruleform))))

            for fname, deriv, term, substep in zip(fnames, derivatives, rule.terms, rule.substeps):
                self.append(self.format_math(sympy.Eq(fname, term)),
                            self.format_text("; to find "),
                            self.format_math(deriv),
                            self.format_text(":"))
                with self.new_level():
                    self.print_rule(substep)
            self.append(self.format_text("The result is: "),
                        self.format_math(diff(rule)))

    def print_Div(self, rule):
        with self.new_step():
            f, g = rule.numerator, rule.denominator
            x = rule.symbol
            ff = sympy.Function("f")(x)
            gg = sympy.Function("g")(x)
            qrule_left = sympy.Derivative(ff / gg, rule.symbol)
            qrule_right = sympy.ratsimp(sympy.diff(sympy.Function("f")(x) /
                                                   sympy.Function("g")(x)))
            qrule = sympy.Eq(qrule_left, qrule_right)
            self.append(self.format_text("Apply the quotient rule, which is:"))
            self.append(self.format_math_display(qrule))
            self.append(self.format_math(sympy.Eq(ff, f)),
                        self.format_text(" and "),
                        self.format_math(sympy.Eq(gg, g)))
            self.append(self.format_text("To find "),
                        self.format_math(ff.diff(rule.symbol)),
                        self.format_text(":"))
            with self.new_level():
                self.print_rule(rule.numerstep)
            self.append(self.format_text("To find "),
                        self.format_math(gg.diff(rule.symbol)),
                        self.format_text(":"))
            with self.new_level():
                self.print_rule(rule.denomstep)
            self.append(self.format_text("Now plug in to the quotient rule:"))
            self.append(self.format_math(diff(rule)))

    def print_Chain(self, rule):
        with self.new_step(), self.new_u_vars() as (u, du):
            self.append(self.format_text("Let "),
                        self.format_math(sympy.Eq(u, rule.inner)))
            self.print_rule(replace_u_var(rule.substep, rule.u_var, u))
        with self.new_step():
            self.append(self.format_text("Then, apply the chain rule. Multiply by "),
                        self.format_math(sympy.Derivative(rule.inner, rule.symbol)),
                        self.format_text(":"))
            if isinstance(rule.innerstep, FunctionRule):
                self.append(self.format_math_display(diff(rule)))
            else:
                with self.new_level():
                    self.print_rule(rule.innerstep)
                self.append(self.format_text("The result of the chain rule is:"))
                self.append(self.format_math_display(diff(rule)))

    def print_Trig(self, rule):
        with self.new_step():
            if isinstance(rule.f, sympy.sin):
                self.append(self.format_text("The derivative of sine is cosine:"))
            elif isinstance(rule.f, sympy.cos):
                self.append(self.format_text("The derivative of cosine is negative sine:"))
            elif isinstance(rule.f, sympy.sec):
                self.append(self.format_text("The derivative of secant is secant times tangent:"))
            elif isinstance(rule.f, sympy.csc):
                self.append(self.format_text("The derivative of cosecant is negative cosecant times cotangent:"))
            self.append(self.format_math_display(sympy.Eq(sympy.Derivative(rule.f, rule.symbol), diff(rule))))

    def print_Exp(self, rule):
        with self.new_step():
            if rule.base == sympy.E:
                self.append(self.format_text("The derivative of "),
                            self.format_math(sympy.exp(rule.symbol)),
                            self.format_text(" is itself."))
            else:
                self.append(self.format_math(sympy.Eq(sympy.Derivative(rule.f, rule.symbol), diff(rule))))

    def print_Log(self, rule):
        with self.new_step():
            assert rule.base == sympy.E
            self.append(self.format_text("The derivative of "),
                        self.format_math(rule.context),
                        self.format_text(" is "),
                        self.format_math(diff(rule)))

    def print_Rewrite(self, rule):
        with self.new_step():
            self.append(self.format_text("Rewrite the function to be differentiated:"))
            self.append(self.format_math_display(sympy.Eq(rule.context, rule.rewritten)))
            self.print_rule(rule.substep)

    def print_Function(self, rule):
        with self.new_step():
            self.append(self.format_text("Trivial:"))
            self.append(self.format_math_display(sympy.Eq(sympy.Derivative(rule.context, rule.symbol), diff(rule),
                                                          evaluate=False)))

    def print_DontKnow(self, rule):
        with self.new_step():
            self.append(self.format_text("Don't know the steps in finding this derivative."))
            self.append(self.format_text("But the derivative is"))
            self.append(self.format_math_display(diff(rule)))

    def print_Alternative(self, rule):
        if rule.context.func in self.alternative_functions_printed:
            self.print_rule(rule.alternatives[0])
        elif len(rule.alternatives) == 2:
            self.alternative_functions_printed.add(rule.context.func)
            self.print_rule(rule.alternatives[1])
        else:
            self.alternative_functions_printed.add(rule.context.func)
            with self.new_step():
                self.append(self.format_text("There are multiple ways to do this derivative."))
                for index, r in enumerate(rule.alternatives[1:]):
                    with self.new_collapsible():
                        self.append_header("Method #{}".format(index + 1))
                        with self.new_level():
                            self.print_rule(r)

    def finalize(self):
        answer = diff(self.rule)
        if answer:
            simp = sympy.simplify(answer)
            if simp != answer:
                answer = simp
                with self.new_step():
                    self.append(self.format_text("Now simplify:"))
                    self.append(self.format_math_display(simp))
        return {
            'content': {'level': self.stack},
            'answer': self.format_math_display(answer)
        }


def print_json_steps(function, symbol):
    a = DiffPrinter(diff_steps(function, symbol))
    return a.finalize()
