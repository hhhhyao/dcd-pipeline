---
title: algorithm used to solve non-linear least squares problems
author: Contributors to Wikimedia projects
date: "2004-11-13T11:11:29Z"
url: "https://en.wikipedia.org/wiki/Gauss%E2%80%93Newton_algorithm"
tags:
  - Optimization algorithms and methods
  - Least squares
  - Statistical algorithms
code_source: "https://github.com/agi-otw/dcd_pipeline"
---

[![Regression pic assymetrique](//upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Regression_pic_assymetrique.gif/500px-Regression_pic_assymetrique.gif)](https://en.wikipedia.org/wiki/File:Regression_pic_assymetrique.gif)

*Fitting of a noisy curve by an asymmetrical peak model $f_{\beta }(x)$ with parameters $\beta$ by mimimizing the sum of squared residuals $r_{i}(\beta )=y_{i}-f_{\beta }(x_{i})$ at grid points $x_{i}$, using the Gauss–Newton algorithm.  
Top: Raw data and model.  
Bottom: Evolution of the normalised sum of the squares of the errors.*

The **Gauss–Newton algorithm** is used to solve non-linear least squares problems, which is equivalent to minimizing a sum of squared function values. It is an extension of Newton's method for finding a minimum of a non-linear function. Since a sum of squares must be nonnegative, the algorithm can be viewed as using Newton's method to iteratively approximate zeroes of the components of the sum, and thus minimizing the sum. In this sense, the algorithm is also an effective method for solving overdetermined systems of equations. It has the advantage that second derivatives, which can be challenging to compute, are not required.[1]

Non-linear least squares problems arise, for instance, in non-linear regression, where parameters in a model are sought such that the model is in good agreement with available observations.

The method is named after the mathematicians Carl Friedrich Gauss and Isaac Newton, and first appeared in Gauss's 1809 work *Theoria motus corporum coelestium in sectionibus conicis solem ambientum*.[2]

## Description

Given $m$ functions ${\textbf {r}}=(r_{1},\ldots ,r_{m})$ (often called residuals) of $n$ variables ${\boldsymbol {\beta }}=(\beta _{1},\ldots \beta _{n}),$ with $m\geq n,$ the Gauss–Newton algorithm iteratively finds the value of $\beta$ that minimize the sum of squares[3] $$S({\boldsymbol {\beta }})=\sum _{i=1}^{m}r_{i}({\boldsymbol {\beta }})^{2}.$$

Starting with an initial guess ${\boldsymbol {\beta }}^{(0)}$ for the minimum, the method proceeds by the iterations
$${\boldsymbol {\beta }}^{(s+1)}={\boldsymbol {\beta }}^{(s)}-\left(\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {J_{r}} \right)^{-1}\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right),$$

where, if **r** and ***β*** are column vectors, the entries of the Jacobian matrix are
$$\left(\mathbf {J_{r}} \right)_{ij}={\frac {\partial r_{i}\left({\boldsymbol {\beta }}^{(s)}\right)}{\partial \beta _{j}}},$$

and the symbol $^{\operatorname {T} }$ denotes the matrix transpose.

At each iteration, the update $\Delta ={\boldsymbol {\beta }}^{(s+1)}-{\boldsymbol {\beta }}^{(s)}$ can be found by rearranging the previous equation in the following two steps:

- $\Delta =-\left(\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {J_{r}} \right)^{-1}\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right)$
- $\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {J_{r}} \Delta =-\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right)$

With substitutions $A=\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {J_{r}}$, $\mathbf {b} =-\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right)$, and $\mathbf {x} =\Delta$, this turns into the conventional matrix equation of form $A\mathbf {x} =\mathbf {b}$, which can then be solved in a variety of methods (see Notes).

If *m* = *n*, the iteration simplifies to

$${\boldsymbol {\beta }}^{(s+1)}={\boldsymbol {\beta }}^{(s)}-\left(\mathbf {J_{r}} \right)^{-1}\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right),$$

which is a direct generalization of Newton's method in one dimension.

In data fitting, where the goal is to find the parameters ${\boldsymbol {\beta }}$ such that a given model function $\mathbf {f} (\mathbf {x} ,{\boldsymbol {\beta }})$ best fits some data points $(x_{i},y_{i})$, the functions $r_{i}$are the residuals:
$$r_{i}({\boldsymbol {\beta }})=y_{i}-f\left(x_{i},{\boldsymbol {\beta }}\right).$$

Then, the Gauss–Newton method can be expressed in terms of the Jacobian $\mathbf {J_{f}} =-\mathbf {J_{r}}$ of the function $\mathbf {f}$ as
$${\boldsymbol {\beta }}^{(s+1)}={\boldsymbol {\beta }}^{(s)}+\left(\mathbf {J_{f}} ^{\operatorname {T} }\mathbf {J_{f}} \right)^{-1}\mathbf {J_{f}} ^{\operatorname {T} }\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right).$$

Note that $\left(\mathbf {J_{f}} ^{\operatorname {T} }\mathbf {J_{f}} \right)^{-1}\mathbf {J_{f}} ^{\operatorname {T} }$ is the left pseudoinverse of $\mathbf {J_{f}}$.

## Notes

The assumption *m* ≥ *n* in the algorithm statement is necessary, as otherwise the matrix $\mathbf {J_{r}} ^{T}\mathbf {J_{r}}$ is not invertible and the normal equations cannot be solved (at least uniquely).

The Gauss–Newton algorithm can be derived by linearly approximating the vector of functions *r**i*. Using Taylor's theorem, we can write at every iteration:
$$\mathbf {r} ({\boldsymbol {\beta }})\approx \mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right)+\mathbf {J_{r}} \left({\boldsymbol {\beta }}^{(s)}\right)\Delta$$

with $\Delta ={\boldsymbol {\beta }}-{\boldsymbol {\beta }}^{(s)}$. The task of finding $\Delta$ minimizing the sum of squares of the right-hand side; i.e.,
$$\min \left\|\mathbf {r} \left({\boldsymbol {\beta }}^{(s)}\right)+\mathbf {J_{r}} \left({\boldsymbol {\beta }}^{(s)}\right)\Delta \right\|_{2}^{2},$$

is a linear least-squares problem, which can be solved explicitly, yielding the normal equations in the algorithm.

The normal equations are *n* simultaneous linear equations in the unknown increments $\Delta$. They may be solved in one step, using Cholesky decomposition, or, better, the QR factorization of $\mathbf {J_{r}}$. For large systems, an iterative method, such as the conjugate gradient method, may be more efficient. If there is a linear dependence between columns of **J****r**, the iterations will fail, as $\mathbf {J_{r}} ^{T}\mathbf {J_{r}}$ becomes singular.

When $\mathbf {r}$ is complex $\mathbf {r} :\mathbb {C} ^{n}\to \mathbb {C}$ the conjugate form should be used: $\left({\overline {\mathbf {J_{r}} }}^{\operatorname {T} }\mathbf {J_{r}} \right)^{-1}{\overline {\mathbf {J_{r}} }}^{\operatorname {T} }$.

## Example

[![Gauss Newton illustration](//upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Gauss_Newton_illustration.png/500px-Gauss_Newton_illustration.png)](https://en.wikipedia.org/wiki/File:Gauss_Newton_illustration.png)

*Calculated curve obtained with ${\hat {\beta }}_{1}=0.362$ and ${\hat {\beta }}_{2}=0.556$ (in blue) versus the observed data (in red)*

In this example, the Gauss–Newton algorithm will be used to fit a model to some data by minimizing the sum of squares of errors between the data and model's predictions.

In a biology experiment studying the relation between substrate concentration [*S*] and reaction rate in an enzyme-mediated reaction, the data in the following table were obtained.

| i | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [*S*] | 0.038 | 0.194 | 0.425 | 0.626 | 1.253 | 2.500 | 3.740 |
| Rate | 0.050 | 0.127 | 0.094 | 0.2122 | 0.2729 | 0.2665 | 0.3317 |

It is desired to find a curve (model function) of the form
$${\text{rate}}={\frac {V_{\text{max}}\cdot [S]}{K_{M}+[S]}}$$

that fits best the data in the least-squares sense, with the parameters $V_{\text{max}}$ and $K_{M}$ to be determined.

Denote by $x_{i}$ and $y_{i}$ the values of [*S*] and **rate** respectively, with $i=1,\dots ,7$. Let $\beta _{1}=V_{\text{max}}$ and $\beta _{2}=K_{M}$. We will find $\beta _{1}$ and $\beta _{2}$ such that the sum of squares of the residuals
$$r_{i}=y_{i}-{\frac {\beta _{1}x_{i}}{\beta _{2}+x_{i}}},\quad (i=1,\dots ,7)$$

is minimized.

The Jacobian $\mathbf {J_{r}}$ of the vector of residuals $r_{i}$ with respect to the unknowns $\beta _{j}$ is a $7\times 2$ matrix with the $i$-th row having the entries
$${\frac {\partial r_{i}}{\partial \beta _{1}}}=-{\frac {x_{i}}{\beta _{2}+x_{i}}};\quad {\frac {\partial r_{i}}{\partial \beta _{2}}}={\frac {\beta _{1}\cdot x_{i}}{\left(\beta _{2}+x_{i}\right)^{2}}}.$$

Starting with the initial estimates of $\beta _{1}=0.9$ and $\beta _{2}=0.2$, after five iterations of the Gauss–Newton algorithm, the optimal values ${\hat {\beta }}_{1}=0.362$ and ${\hat {\beta }}_{2}=0.556$ are obtained. The sum of squares of residuals decreased from the initial value of 1.445 to 0.00784 after the fifth iteration. The plot in the figure on the right shows the curve determined by the model for the optimal parameters with the observed data.

## Convergence properties

The Gauss-Newton iteration is guaranteed to converge toward a local minimum point ${\hat {\beta }}$ under 4 conditions:[4] The functions $r_{1},\ldots ,r_{m}$ are twice continuously differentiable in an open convex set $D\ni {\hat {\beta }}$, the Jacobian $\mathbf {J} _{\mathbf {r} }({\hat {\beta }})$ is of full column rank, the initial iterate $\beta ^{(0)}$ is near ${\hat {\beta }}$, and the local minimum value $|S({\hat {\beta }})|$ is small. The convergence is quadratic if $|S({\hat {\beta }})|=0$.

It can be shown[5] that the increment Δ is a descent direction for *S*, and, if the algorithm converges, then the limit is a stationary point of *S*. For large minimum value $|S({\hat {\beta }})|$, however, convergence is not guaranteed, not even local convergence as in Newton's method, or convergence under the usual Wolfe conditions.[6]

The rate of convergence of the Gauss–Newton algorithm can approach quadratic.[7] The algorithm may converge slowly or not at all if the initial guess is far from the minimum or the matrix $\mathbf {J_{r}^{\operatorname {T} }J_{r}}$ is ill-conditioned. For example, consider the problem with $m=2$ equations and $n=1$ variable, given by
$${\begin{aligned}r_{1}(\beta )&=\beta +1,\\r_{2}(\beta )&=\lambda \beta ^{2}+\beta -1.\end{aligned}}$$

For $\lambda <1$, $\beta =0$ is a local optimum. If $\lambda =0$, then the problem is in fact linear and the method finds the optimum in one iteration. If |λ| < 1, then the method converges linearly and the error decreases asymptotically with a factor |λ| at every iteration. However, if |λ| > 1, then the method does not even converge locally.[8]

## Solving overdetermined systems of equations

The Gauss-Newton iteration
$$\mathbf {x} ^{(k+1)}=\mathbf {x} ^{(k)}-J(\mathbf {x} ^{(k)})^{\dagger }\mathbf {f} (\mathbf {x} ^{(k)})\,,\quad k=0,1,\ldots$$
is an effective method for solving overdetermined systems of equations in the form of $\mathbf {f} (\mathbf {x} )=\mathbf {0}$ with
$$\mathbf {f} (\mathbf {x} )={\begin{bmatrix}f_{1}(x_{1},\ldots ,x_{n})\\\vdots \\f_{m}(x_{1},\ldots ,x_{n})\end{bmatrix}}$$
and $m>n$ where $J(\mathbf {x} )^{\dagger }$ is the Moore-Penrose inverse (also known as pseudoinverse) of the Jacobian matrix $J(\mathbf {x} )$ of $\mathbf {f} (\mathbf {x} )$.
It can be considered an extension of Newton's method and enjoys the same local quadratic convergence [4] toward isolated regular solutions.

If the solution doesn't exist but the initial iterate $\mathbf {x} ^{(0)}$ is near a point ${\hat {\mathbf {x} }}=({\hat {x}}_{1},\ldots ,{\hat {x}}_{n})$ at which the sum of squares $\sum _{i=1}^{m}|f_{i}(x_{1},\ldots ,x_{n})|^{2}\equiv \|\mathbf {f} (\mathbf {x} )\|_{2}^{2}$ reaches a small local minimum, the Gauss-Newton iteration linearly converges to ${\hat {\mathbf {x} }}$. The point ${\hat {\mathbf {x} }}$ is often called a least squares solution of the overdetermined system.

## Derivation from Newton's method

In what follows, the Gauss–Newton algorithm will be derived from Newton's method for function optimization via an approximation. As a consequence, the rate of convergence of the Gauss–Newton algorithm can be quadratic under certain regularity conditions. In general (under weaker conditions), the convergence rate is linear.[9]

The recurrence relation for Newton's method for minimizing a function *S* of parameters ${\boldsymbol {\beta }}$ is
$${\boldsymbol {\beta }}^{(s+1)}={\boldsymbol {\beta }}^{(s)}-\mathbf {H} ^{-1}\mathbf {g} ,$$

where **g** denotes the gradient vector of *S*, and **H** denotes the Hessian matrix of *S*.

Since $S=\sum _{i=1}^{m}r_{i}^{2}$, the gradient is given by
$$g_{j}=2\sum _{i=1}^{m}r_{i}{\frac {\partial r_{i}}{\partial \beta _{j}}}.$$

Elements of the Hessian are calculated by differentiating the gradient elements, $g_{j}$, with respect to $\beta _{k}$:
$$H_{jk}=2\sum _{i=1}^{m}\left({\frac {\partial r_{i}}{\partial \beta _{j}}}{\frac {\partial r_{i}}{\partial \beta _{k}}}+r_{i}{\frac {\partial ^{2}r_{i}}{\partial \beta _{j}\partial \beta _{k}}}\right).$$

The Gauss–Newton method is obtained by ignoring the second-order derivative terms (the second term in this expression). That is, the Hessian is approximated by
$$H_{jk}\approx 2\sum _{i=1}^{m}J_{ij}J_{ik},$$

where $J_{ij}={\partial r_{i}}/{\partial \beta _{j}}$ are entries of the Jacobian **Jr**. Note that when the exact hessian is evaluated near an exact fit we have near-zero $r_{i}$, so the second term becomes near-zero as well, which justifies the approximation. The gradient and the approximate Hessian can be written in matrix notation as
$$\mathbf {g} =2{\mathbf {J} _{\mathbf {r} }}^{\operatorname {T} }\mathbf {r} ,\quad \mathbf {H} \approx 2{\mathbf {J} _{\mathbf {r} }}^{\operatorname {T} }\mathbf {J_{r}} .$$

These expressions are substituted into the recurrence relation above to obtain the operational equations
$${\boldsymbol {\beta }}^{(s+1)}={\boldsymbol {\beta }}^{(s)}+\Delta ;\quad \Delta =-\left(\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {J_{r}} \right)^{-1}\mathbf {J_{r}} ^{\operatorname {T} }\mathbf {r} .$$

Convergence of the Gauss–Newton method is not guaranteed in all instances. The approximation
$$\left|r_{i}{\frac {\partial ^{2}r_{i}}{\partial \beta _{j}\partial \beta _{k}}}\right|\ll \left|{\frac {\partial r_{i}}{\partial \beta _{j}}}{\frac {\partial r_{i}}{\partial \beta _{k}}}\right|$$

that needs to hold to be able to ignore the second-order derivative terms may be valid in two cases, for which convergence is to be expected:[10]

1. The function values $r_{i}$ are small in magnitude, at least around the minimum.
2. The functions are only "mildly" nonlinear, so that ${\frac {\partial ^{2}r_{i}}{\partial \beta _{j}\partial \beta _{k}}}$ is relatively small in magnitude.

## Improved versions

With the Gauss–Newton method the sum of squares of the residuals *S* may not decrease at every iteration. However, since Δ is a descent direction, unless $S\left({\boldsymbol {\beta }}^{s}\right)$ is a stationary point, it holds that $S\left({\boldsymbol {\beta }}^{s}+\alpha \Delta \right)<S\left({\boldsymbol {\beta }}^{s}\right)$ for all sufficiently small $\alpha >0$. Thus, if divergence occurs, one solution is to employ a fraction $\alpha$ of the increment vector Δ in the updating formula:
$${\boldsymbol {\beta }}^{s+1}={\boldsymbol {\beta }}^{s}+\alpha \Delta .$$

In other words, the increment vector is too long, but it still points "downhill", so going just a part of the way will decrease the objective function *S*. An optimal value for $\alpha$ can be found by using a line search algorithm, that is, the magnitude of $\alpha$ is determined by finding the value that minimizes *S*, usually using a direct search method in the interval $0<\alpha <1$ or a backtracking line search such as Armijo-line search. Typically, $\alpha$ should be chosen such that it satisfies the Wolfe conditions or the Goldstein conditions.[11]

In cases where the direction of the shift vector is such that the optimal fraction α is close to zero, an alternative method for handling divergence is the use of the Levenberg–Marquardt algorithm, a trust region method.[3] The normal equations are modified in such a way that the increment vector is rotated towards the direction of steepest descent,
$$\left(\mathbf {J^{\operatorname {T} }J+\lambda D} \right)\Delta =-\mathbf {J} ^{\operatorname {T} }\mathbf {r} ,$$

where **D** is a positive diagonal matrix. Note that when **D** is the identity matrix **I** and $\lambda \to +\infty$, then $\lambda \Delta =\lambda \left(\mathbf {J^{\operatorname {T} }J} +\lambda \mathbf {I} \right)^{-1}\left(-\mathbf {J} ^{\operatorname {T} }\mathbf {r} \right)=\left(\mathbf {I} -\mathbf {J^{\operatorname {T} }J} /\lambda +\cdots \right)\left(-\mathbf {J} ^{\operatorname {T} }\mathbf {r} \right)\to -\mathbf {J} ^{\operatorname {T} }\mathbf {r}$, therefore the direction of Δ approaches the direction of the negative gradient $-\mathbf {J} ^{\operatorname {T} }\mathbf {r}$.

The so-called Marquardt parameter $\lambda$ may also be optimized by a line search, but this is inefficient, as the shift vector must be recalculated every time $\lambda$ is changed. A more efficient strategy is this: When divergence occurs, increase the Marquardt parameter until there is a decrease in *S*. Then retain the value from one iteration to the next, but decrease it if possible until a cut-off value is reached, when the Marquardt parameter can be set to zero; the minimization of *S* then becomes a standard Gauss–Newton minimization.

## Large-scale optimization

For large-scale optimization, the Gauss–Newton method is of special interest because it is often (though certainly not always) true that the matrix $\mathbf {J} _{\mathbf {r} }$ is more sparse than the approximate Hessian $\mathbf {J} _{\mathbf {r} }^{\operatorname {T} }\mathbf {J_{r}}$. In such cases, the step calculation itself will typically need to be done with an approximate iterative method appropriate for large and sparse problems, such as the conjugate gradient method.

In order to make this kind of approach work, one needs at least an efficient method for computing the product
$${\mathbf {J} _{\mathbf {r} }}^{\operatorname {T} }\mathbf {J_{r}} \mathbf {p}$$

for some vector **p**. With sparse matrix storage, it is in general practical to store the rows of $\mathbf {J} _{\mathbf {r} }$ in a compressed form (e.g., without zero entries), making a direct computation of the above product tricky due to the transposition. However, if one defines **c***i* as row *i* of the matrix $\mathbf {J} _{\mathbf {r} }$, the following simple relation holds:
$${\mathbf {J} _{\mathbf {r} }}^{\operatorname {T} }\mathbf {J_{r}} \mathbf {p} =\sum _{i}\mathbf {c} _{i}\left(\mathbf {c} _{i}\cdot \mathbf {p} \right),$$

so that every row contributes additively and independently to the product. In addition to respecting a practical sparse storage structure, this expression is well suited for parallel computations. Note that every row **c***i* is the gradient of the corresponding residual *r**i*; with this in mind, the formula above emphasizes the fact that residuals contribute to the problem independently of each other.

## Related algorithms

In a quasi-Newton method, such as that due to Davidon, Fletcher and Powell or Broyden–Fletcher–Goldfarb–Shanno (BFGS method) an estimate of the full Hessian ${\frac {\partial ^{2}S}{\partial \beta _{j}\partial \beta _{k}}}$ is built up numerically using first derivatives ${\frac {\partial r_{i}}{\partial \beta _{j}}}$ only so that after *n* refinement cycles the method closely approximates to Newton's method in performance. Note that quasi-Newton methods can minimize general real-valued functions, whereas Gauss–Newton, Levenberg–Marquardt, etc. fits only to nonlinear least-squares problems.

Another method for solving minimization problems using only first derivatives is gradient descent. However, this method does not take into account the second derivatives even approximately. Consequently, it is highly inefficient for many functions, especially if the parameters have strong interactions.

## Example implementations

### Julia

The following implementation in Julia provides one method which uses a provided Jacobian and another computing with automatic differentiation.

```
"""
    gaussnewton(r, J, β₀, maxiter, tol)

Perform Gauss–Newton optimization to minimize the residual function `r` with Jacobian `J` starting from `β₀`. The algorithm terminates when the norm of the step is less than `tol` or after `maxiter` iterations.
"""
function gaussnewton(r, J, β₀, maxiter, tol)
    β = copy(β₀)
    for _ in 1:maxiter
        Jβ = J(β);
        Δ  = -(Jβ' * Jβ) \ (Jβ' * r(β))
        β += Δ
        if sqrt(sum(abs2, Δ)) < tol
            break
        end
    end
    return β
end

import AbstractDifferentiation as AD, Zygote
backend = AD.ZygoteBackend() # other backends are available

"""
    gaussnewton(r, β₀, maxiter, tol)

Perform Gauss–Newton optimization to minimize the residual function `r` starting from `β₀`. The relevant Jacobian is calculated using automatic differentiation. The algorithm terminates when the norm of the step is less than `tol` or after `maxiter` iterations.
"""
function gaussnewton(r, β₀, maxiter, tol)
    β = copy(β₀)
    for _ in 1:maxiter
        rβ, Jβ = AD.value_and_jacobian(backend, r, β)
        Δ  = -(Jβ[1]' * Jβ[1]) \ (Jβ[1]' * rβ)
        β += Δ
        if sqrt(sum(abs2, Δ)) < tol
            break
        end
    end
    return β
end

```

## Notes

1. **^** Mittelhammer, Ron C.; Miller, Douglas J.; Judge, George G. (2000). *Econometric Foundations*. Cambridge: Cambridge University Press. pp. 197–198. ISBN 0-521-62394-4.
2. **^** Floudas, Christodoulos A.; Pardalos, Panos M. (2008). *Encyclopedia of Optimization*. Springer. p. 1130. ISBN 9780387747583.
3. ^ ***a*** ***b*** Björck (1996)
4. ^ ***a*** ***b*** J.E. Dennis, Jr. and R.B. Schnabel (1983). *Numerical Methods for Unconstrained Optimization and Nonlinear Equations*. SIAM 1996 reproduction of Prentice-Hall 1983 edition. p. 222.
5. **^** Björck (1996), p. 260.
6. **^** Mascarenhas (2013), "The divergence of the BFGS and Gauss Newton Methods", *Mathematical Programming*, **147** (1): 253–276, arXiv:1309.7922, doi:10.1007/s10107-013-0720-6, S2CID 14700106
7. **^** Björck (1996), p. 341, 342.
8. **^** Fletcher (1987), p. 113.
9. **^** "Archived copy" (PDF). Archived from the original (PDF) on 2016-08-04. Retrieved 2014-04-25.
10. **^** Nocedal (1999), p. 259.
11. **^** Nocedal, Jorge. (1999). *Numerical optimization*. Wright, Stephen J., 1960-. New York: Springer. ISBN 0387227423. OCLC 54849297.

## References

- Björck, A. (1996). *Numerical methods for least squares problems*. SIAM, Philadelphia. ISBN 0-89871-360-9.
- Fletcher, Roger (1987). *Practical methods of optimization* (2nd ed.). New York: John Wiley & Sons. ISBN 978-0-471-91547-8..
- Nocedal, Jorge; Wright, Stephen (1999). *Numerical optimization*. New York: Springer. ISBN 0-387-98793-2.

## External links

- *Probability, Statistics and Estimation* The algorithm is detailed and applied to the biology experiment discussed as an example in this article (page 84 with the uncertainties on the estimated values).

### Implementations

- Artelys Knitro is a non-linear solver with an implementation of the Gauss–Newton method. It is written in C and has interfaces to C++/C#/Java/Python/MATLAB/R.
