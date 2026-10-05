# Maths

In this repository I try some simple math problems in different programming languages.

## Infinite nested radical

The first project solves for `x` when the user enters `y` in:

$$
x + \sqrt{x + \sqrt{x + \sqrt{x + \dots}}} = y
$$

The nested radical equals $\sqrt{y}$, so the solution is:

$$
x = y - \sqrt{y}
$$

## ASCII Mandelbrot set

The second project draws a Mandelbrot fractal directly in the terminal. For
each point $c$, it repeats:

$$
z_{n+1} = z_n^2 + c, \qquad z_0 = 0
$$

Points that do not escape are drawn with `@`; the other characters show how
quickly the sequence grows beyond the escape radius.

Compile and run it with a C++17 compiler:

```sh
c++ -std=c++17 -O2 mandelbrot.cpp -o mandelbrot
./mandelbrot
```

## Logistic map and the route to chaos

`logistic_map.cpp` iterates a simple nonlinear recurrence:

$$
x_{n+1} = r x_n(1-x_n), \qquad 0 \leq r \leq 4
$$

Its ASCII bifurcation diagram samples rates from 2.5 to 4.0. A single branch
splits into two, then four, before densely filled regions and periodic windows
appear. Each `*` marks a vertical bin visited by the sampled orbit. The separate
report for your chosen rate prints the last eight retained states and estimates
local sensitivity using the mean of $\ln|r(1-2x_n)|$. A positive estimate suggests
local expansion along the sampled orbit; a negative one suggests contraction.
The estimate is `-inf` when a sampled derivative is zero.

Try rates `2.8`, `3.2`, and `3.5` to see approximately one, two, and four repeating
values, then `3.9` for an irregular orbit. Every run starts at
$x_0=0.3141592653589793$ and discards 1000 updates. Finite precision, finite sample
counts, and the coarse grid limit the picture: the discarded updates do not
guarantee convergence, narrow windows can be missed, and the sensitivity
estimate does not prove chaos or a period.

Optional arguments are rate (0-4), retained samples per orbit (16-4096), width
(21-161), and height (11-61); defaults: `3.9 256 81 25`. The rate changes the
numeric report; the diagram always spans 2.5-4.0.

```sh
c++ -std=c++17 -O2 logistic_map.cpp -o logistic_map
./logistic_map
./logistic_map 3.2 512 101 31
python3 tests/test_logistic_map.py
```

The test script uses only Python's standard library, builds in a temporary
directory, and accepts `CXX`, `CPPFLAGS`, and `CXXFLAGS` overrides.

## Ulam prime spiral

`ulam_spiral.cpp` places the positive integers in a square spiral and marks
every prime number with `##`. The primes form surprisingly strong diagonal
patterns even though they become less common as the numbers grow.

Compile it with a C++17 compiler and optionally choose an odd grid size from 5
to 99 (the default is 31):

```sh
c++ -std=c++17 -O2 ulam_spiral.cpp -o ulam_spiral
./ulam_spiral 41
```

## Pascal / Sierpinski triangle

Mark only the odd numbers in Pascal's triangle and a Sierpinski pattern appears.
`pascal_sierpinski.cpp` draws those coefficients as `*`. It checks whether
`column & (row - column)` is zero, avoiding factorials and integer overflow.
Choose 1-64 rows (default: 32); powers of two show complete stages of the pattern.

```sh
c++ -std=c++17 -O2 pascal_sierpinski.cpp -o pascal_sierpinski
./pascal_sierpinski 32
```

## Lissajous curves

Combine two oscillations, $x(t) = \cos(at)$ and $y(t) = \sin(bt)$, into a
closed curve. `lissajous.cpp` samples one complete period on an ASCII canvas.
Try `1 1` for a circle in mathematical coordinates (its terminal appearance
depends on character proportions), or `3 2` and `5 4` for interlaced loops.
Both integer frequencies must be 1-9; the defaults are `3 2`.

```sh
c++ -std=c++17 -O2 lissajous.cpp -o lissajous
./lissajous 5 4
```

## Collatz explorer

Start with a positive integer: halve it when even, or replace it with $3n+1$
when odd. `collatz.cpp` prints the trajectory, steps to reach 1, and peak value.
For example, 27 takes 111 steps and reaches 9232. Whether **every** positive
integer eventually reaches 1 is still an unproved conjecture.

The default start is 27. An optional second argument caps the steps at 1-10000
(default: 10000). The program stops with exit code 2 if that limit is reached
before 1, or before a calculation would overflow a 64-bit unsigned integer;
invalid arguments return 1.

```sh
c++ -std=c++17 -O2 collatz.cpp -o collatz
./collatz 27
./collatz 27 20
```

## Birthday paradox

How many people are needed before a shared birthday becomes more likely than
not? `birthday_paradox.cpp` calculates the probability of at least one matching
pair and draws a table with percentage bars. At 23 people it is about 50.73%.

The model assumes independent birthdays distributed uniformly across 365 days,
ignoring leap days. It computes the complement of all birthdays being different:

$$
P(\text{shared}) = 1 - \prod_{k=0}^{n-1}\frac{365-k}{365}, \qquad 0 \leq n \leq 365
$$

For zero or one person the probability is zero; for 366 people it is one.
Choose 0-366 people to highlight in the table (default: 23).

```sh
c++ -std=c++17 -O2 birthday_paradox.cpp -o birthday_paradox
./birthday_paradox 23
```

## Gambler's ruin

`gamblers_ruin.cpp` follows a bankroll that gains one unit with probability $p$
and loses one with probability $q=1-p$. A trial stops at 0 or a chosen target
$N$. The program plots the first trial in ASCII, compares a seeded simulation
with theory, and shows how success probability changes with the starting
bankroll $i$. Even a fair game only reaches the target with probability $i/N$.

For a fair walk ($p=q=1/2$), success probability and expected stopping time are:

$$
P_i = \frac{i}{N}, \qquad E_i[T] = i(N-i)
$$

For $0<p<1$ and $p\ne q$:

$$
P_i = \frac{1-(q/p)^i}{1-(q/p)^N}, \qquad
E_i[T] = \frac{i-NP_i}{q-p}
$$

The program handles $p=0$, $p=1$, and initial boundary states separately. It
evaluates these exact model formulas in floating-point arithmetic, using a
rescaled form to avoid large powers. Trials use independent pseudorandom steps;
the same arguments reproduce the experiment across standard C++ libraries.

Optional arguments are start (0-target), target (2-40), integer win percentage
(0-100), trials (1-10000), seed (0-4294967295), and step limit per trial
(1-10000). Defaults: `10 20 50 10000 42 10000`. The path preview shows at most
60 updates and reports omitted updates. Work is capped at 100 million walk
updates. Invalid arguments return 1; any unresolved trial makes the program
return 2. Such trials remain separate from wins and losses: the output gives
bounds on this batch's eventual success fraction and the mean of the capped
durations. These bounds describe unresolved outcomes, rather than statistical
confidence in the theoretical probability.

```sh
c++ -std=c++17 -O2 gamblers_ruin.cpp -o gamblers_ruin
./gamblers_ruin 10 20 50
./gamblers_ruin 10 20 45 10000 123
./gamblers_ruin 2 4 50 20 42 1  # All trials unresolved; exits 2.
python3 tests/test_gamblers_ruin.py
```

The test script needs Python 3 and a C++17 compiler (`CXX`, `CPPFLAGS`, and
`CXXFLAGS` are supported). It checks the formulas against an exact absorbing
Markov chain calculation, plus boundary states, seeded runs, and step limits.

## Pi convergence race

`pi_convergence.cpp` compares two alternating series for $\pi$:

$$
\text{Leibniz:}\quad \pi = 4\sum_{k=0}^{\infty}\frac{(-1)^k}{2k+1}
$$

$$
\text{Nilakantha:}\quad \pi = 3 + \sum_{k=1}^{\infty}\frac{4(-1)^{k+1}}{(2k)(2k+1)(2k+2)}
$$

Each update adds one term to both series (Nilakantha starts at 3). A table at
1, 10, 100, ... updates, plus your final count, shows the estimates and their
absolute errors against the standard library's value of $\pi$. Nilakantha
converges much faster, but floating-point rounding eventually limits accuracy;
a displayed zero error does not mean the result is mathematically exact.
Choose 1-1000000 updates (default: 10000).

```sh
c++ -std=c++17 -O2 pi_convergence.cpp -o pi_convergence
./pi_convergence 10000
```

## Magic squares

`magic_square.cpp` arranges every integer from 1 to $n^2$ exactly once so that
every row, column, and both main diagonals have the same sum:

$$
M = \frac{n(n^2+1)}{2}
$$

It uses the Siamese method: start at the top center, step up and right with
wraparound, and move down instead if the next cell is occupied. Choose an odd
size from 1 to 25 (default: 5). A 3-by-3 square has magic sum 15.

```sh
c++ -std=c++17 -O2 magic_square.cpp -o magic_square
./magic_square 5
```

## Spanning trees and Kirchhoff's theorem

A spanning tree connects every vertex of a graph without forming a cycle.
`spanning_trees.cpp` counts these trees exactly and can report how often each
edge appears in them. The default 3-by-3 grid has 192 spanning trees.

The graph's Laplacian $L=D-A$ has vertex degrees on the diagonal, $-1$ for
adjacent vertices, and zero elsewhere. Kirchhoff's matrix-tree theorem gives:

$$
\tau(G) = \det L_{\widehat r}
$$

Here $L_{\widehat r}$ removes row and column $r$. The program displays the
matrix obtained by removing the last vertex. It evaluates the determinant
with fraction-free Bareiss elimination and exact 64-bit integer arithmetic.
The graph-size limits keep all intermediate calculations within that range.

With `--edge-stats`, each edge $e=\{u,v\}$ gets an inclusion count and the
exact probability that it belongs to a uniformly chosen spanning tree:

$$
N_e = \det L_{\widehat{u,v}}, \qquad P(e\in T)=\frac{N_e}{\tau(G)}
$$

The second matrix removes both endpoint rows and columns while retaining the
original degrees. This counts trees containing $e$: contract the edge, then
delete the merged vertex from its Laplacian. Fractions are reduced. An edge
with probability 1 is a **bridge**; removing it disconnects the graph. The
inclusion counts sum to $(n-1)\tau(G)$, since every tree has $n-1$ edges.

Invoke it as `./spanning_trees [family [size [edges]]] [--edge-stats]`:

| Family | Size | Graph |
| --- | --- | --- |
| `path` | 1-10 vertices | A chain |
| `cycle` | 3-10 vertices | One closed loop |
| `complete` | 1-10 vertices | Every pair connected |
| `grid` | Side length 1-3 | A square grid, without wrapping |
| `custom` | 1-10 vertices | Explicit edges required |

Defaults are `grid 3`; each built-in family uses size 3 when omitted. Vertex
labels start at 0; grid labels run left to right, top to bottom. `custom`
requires both size and a comma-separated edge list such as `0-1,1-2,2-3`.
Use `-` for no edges. The graph is simple and undirected: self-loops, duplicate
edges (including reversed duplicates), out-of-range vertices, and whitespace
inside an argument are rejected. Edge order and orientation do not affect
the result.

`--edge-stats` may appear once anywhere among the arguments. Use `--help`
alone for usage. Exit codes are 0 for connected graphs or help, 1 for invalid
arguments, and 2 for disconnected graphs. Disconnected graphs have zero
spanning trees and no edge probabilities. A single vertex has one empty tree;
the determinant of its empty cofactor is 1.

```sh
c++ -std=c++17 -O2 spanning_trees.cpp -o spanning_trees
./spanning_trees --edge-stats
./spanning_trees complete 10 --edge-stats  # 100,000,000 trees; each edge has probability 1/5.
./spanning_trees custom 4 0-1,0-2,1-2,2-3 --edge-stats  # Edge 2-3 is a bridge.
./spanning_trees custom 4 0-1,2-3  # Disconnected; exits 2.
python3 tests/test_spanning_trees.py
```

The Python standard-library tests compare the executable with independent
tree enumeration, check the printed matrix and exact edge fractions, and
cover graph families, arbitrary vertex labels, disconnected graphs, input
validation, and the supported limits. They compile in a temporary directory and accept `CXX`,
`CPPFLAGS`, and `CXXFLAGS`. See also the
[MIT notes on the matrix-tree theorem](https://math.mit.edu/~apost/courses/18.212_2021/lectures/18212_lecture19.pdf).

## Lights Out and binary linear algebra

`lights_out.cpp` solves a square Lights Out puzzle. Pressing a cell toggles its
light and each orthogonal neighbor. Edges do not wrap. The goal is to switch
every light off using the fewest presses.

Pressing twice cancels, and press order does not matter. Write the board as a
binary vector $b$ and the press pattern as $x$. If $A$ records which lights
each press toggles, the puzzle becomes:

$$
Ax = b \pmod{2}
$$

Gauss-Jordan elimination uses XOR for row operations. A contradictory row
$0=1$ means the board is impossible. Otherwise, a particular solution $x_0$
and a basis $v_1,\ldots,v_k$ of the kernel give every solution:

$$
x = x_0 + c_1v_1 + \cdots + c_kv_k, \qquad c_i \in \{0,1\}
$$

The program checks all $2^k$ patterns to find the exact minimum number of
presses. It reports the matrix rank, nullity $k$, solution count, minimum
presses, and number of minimum patterns. Ties use row-major lexicographic
order: read left to right, top to bottom, preferring `0` to `1`. Counts refer
to patterns with each cell pressed at most once, not different move orders.

Invoke it as `./lights_out [size [board]] [--basis]`. Choose a size from 1 to 10
(default: 5). An optional board must contain exactly that many slash-separated
binary rows, each of that width, with `1` meaning on. Without a board, every
light starts on. The default 5-by-5 board has rank 23, nullity 2, and four
solutions, all requiring 15 presses.

`--basis` may appear once, before, between, or after the positional arguments;
it displays independent press patterns that leave any board unchanged, even
for an impossible board. Use `--help` alone for usage. Invalid arguments return
1, impossible boards return 2, and solved boards or help return 0.

The search is small even at the supported limit: the first press row determines
each later row by clearing the lights immediately above. Thus at most $2^n$
solutions exist for an $n$-by-$n$ board, so at most 1024 patterns need checking.
All calculations are exact binary arithmetic.

```sh
c++ -std=c++17 -O2 lights_out.cpp -o lights_out
./lights_out
./lights_out 3 010/111/010   # One press at the center solves this cross.
./lights_out 4 --basis
./lights_out 5 10000/00000/00000/00000/00000  # Impossible; exits 2.
python3 tests/test_lights_out.py
```

The Python standard-library tests use an independent row-chasing solver,
exhaust every board up to 3-by-3, and check minimum patterns, kernel bases,
impossible boards, input validation, and all supported sizes. They compile
in a temporary directory and support `CXX`, `CPPFLAGS`, and `CXXFLAGS`.
For the underlying mathematics, see Anderson and Feil's
[Turning Lights Out with Linear Algebra](https://doi.org/10.1080/0025570X.1998.11996658).

## Newton fractal

`newton_fractal.cpp` marks starting points in the complex plane by which root
of $z^3=1$ Newton's method approaches:

$$
z_{n+1} = z_n - \frac{z_n^3-1}{3z_n^2}
$$

Characters `1`, `2`, and `3` identify the roots $1$, $-1/2+i\sqrt{3}/2$, and
$-1/2-i\sqrt{3}/2$. A `?` marks an unresolved point: the iteration limit was
reached, the derivative was too small, or a value was non-finite. Classification
uses a distance tolerance of $10^{-6}$, so this is a finite-precision picture.

The window is $[-2,2]$ on both axes. Optional arguments are width (5-161),
height (5-81), and maximum Newton updates per point (1-200); defaults: `81 41 40`.

```sh
c++ -std=c++17 -O2 newton_fractal.cpp -o newton_fractal
./newton_fractal 81 41 40
```

## Conway's Game of Life

`game_of_life.cpp` evolves a `glider` or `blinker` using Conway's rules:
birth with three live neighbors, and survival with two or three.
The blinker repeats every two updates; away from the boundary, the glider
moves one cell diagonally every four.

`#` marks living cells and `.` marks dead cells. Outside cells stay dead,
and edges do not wrap. The initial board and every generation are printed.
Optional arguments are seed, updates (0-50), width (5-80), and height (5-40);
defaults: `glider 8 20 12`.

```sh
c++ -std=c++17 -O2 game_of_life.cpp -o game_of_life
./game_of_life glider 8
./game_of_life blinker 2 9 9
```

## Abelian sandpile

`abelian_sandpile.cpp` places a pile of grains at the center of a finite square
grid. A cell with at least four grains topples: it loses four and sends one
grain to each orthogonal neighbor. Grains crossing an edge leave the grid.
Redistribution continues until every cell has height 0, 1, 2, or 3.

The resulting geometric pattern has a surprising property: every legal
toppling order gives the same final heights and the same number of topplings
at each cell. Those per-cell counts form the **odometer**. The program shows
the exact final heights beside a grain balance, followed by an activity map
with logarithmic shading relative to that run's maximum. A space means the
cell never toppled; `.:-=+*#%@` shows increasing activity.

Optional arguments are an odd grid size (3-61) and starting grains (0-100000);
defaults: `31 10000`. Add `--odometer` to print exact counts for every cell as
`row column topplings`, using zero-based coordinates. These narrow records are
also convenient for checking the result independently.

For a small example, `3 16` retains 12 grains, loses 4 through the boundary,
and performs 9 topplings. Counts use exact 64-bit integers. A decreasing
potential bounds accepted inputs by 48,050,000 individual topplings; the
implementation combines consecutive topplings at a cell into a batch.

```sh
c++ -std=c++17 -O2 abelian_sandpile.cpp -o abelian_sandpile
./abelian_sandpile
./abelian_sandpile 3 16 --odometer
python3 tests/test_abelian_sandpile.py
```

The Python standard-library tests compare both heights and odometers with a
different legal toppling order, check the exact grain balance at every cell,
and exercise boundaries, symmetry, invalid arguments, and maximum input.
They build in a temporary directory and support `CXX`, `CPPFLAGS`, and
`CXXFLAGS`. For more about the model, see Dhar's
[The Abelian Sandpile and Related Models](https://arxiv.org/abs/cond-mat/9808047).

## Egyptian fractions

`egyptian_fractions.cpp` splits a rational number into distinct unit fractions
by repeatedly choosing the largest one that fits the remainder. For example:

$$
\frac{4}{13} = \frac{1}{4} + \frac{1}{18} + \frac{1}{468}
$$

Optional arguments are numerator (0-1000000) and denominator (1-1000000);
the default is `4 13`. Integer parts remain separate, and zero gives zero.
Arithmetic uses exact 64-bit integers. Before an intermediate denominator would
overflow, or after 32 unit fractions, the program stops with exit code 2 and
prints the exact remaining fraction rather than an incorrect decomposition.

```sh
c++ -std=c++17 -O2 egyptian_fractions.cpp -o egyptian_fractions
./egyptian_fractions 4 13
```

## Pell equations and continued fractions

Approximating a square root with fractions can solve an exact integer equation:

$$
x^2 - Dy^2 = 1
$$

`pell_equation.cpp` expands $\sqrt{D}$ as a periodic continued fraction and
prints each convergent $p/q$, its exact residual $p^2-Dq^2$, and whether it lies
below or above the square root. The first residual of +1 gives the smallest
positive solution. A residual of -1 solves the companion equation with -1 on
the right. If the period has length $L$, the positive solution takes $L$
convergents when $L$ is even, or $2L$ when it is odd, counting the initial
integer term.

The default is $D=13$, giving $649^2-13\cdot180^2=1$. Try $D=61$ for a much
larger surprise: $x=1766319049$ and $y=226153980$. Choose a nonsquare integer
from 2 to 100. All calculations use exact 64-bit integers, with checks before
multiplication; perfect squares and invalid arguments return exit code 1.

```sh
c++ -std=c++17 -O2 pell_equation.cpp -o pell_equation
./pell_equation
./pell_equation 61
```

Run the Python standard-library checks with `python3 tests/test_pell_equation.py`.
They compile into a temporary directory and compare all 90 accepted values
against an independent exact rational-interval calculation. `CXX` and
`CXXFLAGS` can select a compiler and extra flags.

## Josephus circle

`josephus.cpp` removes every $k$-th person from a circle and shows the elimination
order and final survivor. People are numbered from 1; person 1 receives the
first count, and counting restarts at the next person after each removal.
With 7 people and step 3, person 4 remains.

The simulation independently checks its result with the zero-based recurrence
$J(1)=0$, $J(n)=(J(n-1)+k)\bmod n$, then adds one for the displayed numbering.
Optional arguments are people (1-100) and step (1 through $2^{64}-1$);
defaults: `7 3`. Large steps are reduced modulo the circle size.

```sh
c++ -std=c++17 -O2 josephus.cpp -o josephus
./josephus 7 3
```

## Fourier square wave

Build a square wave by adding odd sine harmonics:

$$
S_N(x) = \frac{4}{\pi}\sum_{k=0}^{N-1}\frac{\sin((2k+1)x)}{2k+1}
$$

`fourier_square_wave.cpp` draws the sum beside the target and reports numerical
samples and the first peak. More terms narrow the ripples, but Gibbs overshoot
persists: about 8.949% of the jump between -1 and +1. The plot spans $[-1.5,1.5]$
vertically to include that overshoot. Choose 1-50 terms (default: 8).

```sh
c++ -std=c++17 -O2 fourier_square_wave.cpp -o fourier_square_wave
./fourier_square_wave 20
```

## Galton board

`galton_board.cpp` sends balls through independent, equally likely left/right
choices. The number of right turns selects the final bin. A histogram compares
observed counts with the exact binomial probabilities for $n$ rows:

$$
P(k) = \binom{n}{k}2^{-n}
$$

`#` marks observed counts, and `|` marks expected counts on the same scale.
Optional arguments are rows (1-32), balls (1-1000000), and a seed (0-4294967295);
defaults: `12 10000 42`. Repeating the same arguments repeats the pseudorandom
experiment. The program also reports total balls and observed/theoretical means.

```sh
c++ -std=c++17 -O2 galton_board.cpp -o galton_board
./galton_board 16 50000 123
```
