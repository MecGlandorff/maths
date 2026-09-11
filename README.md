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

## Ulam prime spiral

The third project places the positive integers in a square spiral and marks
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
