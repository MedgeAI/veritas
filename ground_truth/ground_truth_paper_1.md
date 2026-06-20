Title: Human HDAC6 senses valine abundancy to regulate DNA damage

URL: https://www.pubpeer.com/publications/429F23C68462E5C1A09175C3CD8B07

Summary: There are comments on PubPeer for publication: Human HDAC6 senses valine abundancy to regulate DNA damage (2024)

Content:
## Introduction

May and June 2025 a number of issues were reported for this paper:

1.  Overlap in fluorescence images
2.  Impossible numerical data

The paper was corrected July 2025. However, the authors only addressed the image overlaps. The issues with the data are, in my opinion, far worse and mostly compatible with fabrication.

## Impossible data

Comments #5, #7, and #9 show many examples of mathematical relationships between what **should** be independent experimental series. The first author simply responds to this by supplying more detailed, but still impossible, raw data.

In the below I will just focus on one issue identified in #5: the difference between two measurement series in Fig. 4(c) is exactly 0.3% for all 35 rows of measurement data.

shHDAC6(24 h) = hHDAC6(0 h) - 0.3%.

[![file](https://pubpeer.com/storage/image-1775804927658.png)](https://pubpeer.com/storage/image-1775804927658.png)

At the bottom of the post I have appended the digitized version of the raw data that the first author provided in #6.

The author explains several times that the numerical values represent the percentage of cells expressing a certain marker. The cell counting was done on *at least three non-serial sections* and also *at least three microscopic fields were counted per section*. From the authors' raw data we can see this analysis was done on anywhere between 100 and 10,000 cells per microscope field. There is no row-by-row correlation between the total number of cells counted at 0h and 24h. Still, the difference in the percentage of positive cells is exactly 0.3%-point and some odd patterns are visible:

[![file](https://pubpeer.com/storage/image-1775799212788.png)](https://pubpeer.com/storage/image-1775799212788.png)

The main question is: how likely is the above to have happened by chance. I am not fully satisfied with my analysis yet. Still, I get to a probability of less than one in 1022^{22}. And that makes this by far the most significant discovery of this paper. And it also shows the results to be bogus.

## Probability calculation

The raw shHDAC6 data provided by the authors shows for each row exactly a 0.3%-point difference between the 0 h and 24 h values. One can already get a feel of how unlikely this is by looking at the combinations that yield this difference. Take the fourth row. At 0 hr the authors counted 250 cells in total and found 3 positive ones. At 24 h they counted 1000 cells and found 9 positives. The difference in fractions is 3/250 – 9/250 = 0.3%. One can search for other combinations that give this exact difference:

| 0 h / N = 250 | 24 h / M = 1000 |
| --- | --- |
| 1 | 1 |
| 2 | 5 |
| **3** | **9** |
| 4 | 13 |
| … | … |

This already gives an intuitive feeling for how rare this must be: there are many ‘forbidden’ positive counts in the 1000 h set. In fact, there are many total cell count combinations that even cannot yield a 0.3% difference (100-100, 100-200, 100-500, 100-1250, 200-200, 500-500, 500-1250, …). By a stroke of (bad) luck the authors happened to missed these combinations that would have prevented them from finding a 0.3% difference.

I made a numerical analysis of the probability to find a 0.3% difference in the fraction of positive cells between two datasets. The first dataset has a total of N cells, the second dataset M. As shown above, there is only a limited number of combinations (n, m) that result in n/N – m/M = 0.3%. The analysis starts with enumerating all (n, m) pairs that give the desired 0.3% difference.

In the next step the probability of drawing any of these pairs is calculated. The probability of finding n successes in N tries is given by the [binomial probability mass function](https://en.wikipedia.org/wiki/Binomial_distribution#Probability_mass_function):

f(n, N, p\_1) = (Nn)p1n(1−p1)N−n{N\\choose n}p\_1^n {(1-p\_1)}^{N-n}

We know n and N, but p1 is not exactly known. The same holds for our second draw of finding m positives in M cells,

f(m, M, p\_2) = (Mm)p2m(1−p2)M−m{M\\choose m}p\_2^m {(1-p\_2)}^{M-m},

where p2\_2 is not exactly known. To tackle this uncertainty I simply try all somewhat realistic p1\_1\-p2\_2 combinations, see [this Colab script](https://colab.research.google.com/drive/1izxSB5K6xyy7f9aioDJhjb-3sS7Z5aL-#scrollTo=351kyJZq9RCg). Below a representative results:

[![file](https://pubpeer.com/storage/image-1775800343287.png)](https://pubpeer.com/storage/image-1775800343287.png)

The figure shows the probability to find a 0.3% difference as a function of p1\_1 and p2\_2 for N=1000 and M=200.  
It is no surprise to find that this probability is maximum when p1\_1 – p2\_2 = 0.3%. This is the white line in the plot.

In hindsight it is also no surprise to find that the maximum probability of 0.224 is found for p1\_1 = 0.3% and p2\_2 = 0. With p2\_2 0 one will every time find 0 positive cells, so an infinitely sharp distribution. At the same time the low p1\_1 = 0.003 value will give a quite sharp distribution and hence a good chance of actually drawing 3 positive cells from the 1000. The maximum probability of 0.224 is simply (10003)0.0033(1−0.003)1000−3{1000 \\choose 3} 0.003^3 {(1-0.003)}^{1000-3}.

Different N, M total cell count combinations result in a different maximum probability to find a 0.3% difference. I checked all the combinations that the authors report. The 22% probability above is the maximum probability to find a 0.3% difference. The authors report this same difference 35 times in a row. The chance of that happening is 0.22435\=10−230.224^{35} = 10^{-23}. And that is a polite way of saying 'impossible'.

## Caveats

In the above I calculated the probability of finding a 0.3% difference. This is very specific: the paper would also have been flagged when finding any other fixed difference. In practice, the first row is used to observe the actual difference and for the remaining 34 rows it is checked whether these have the exact same difference. When the maximum probability remains 0.22 this would come down to a 0.2234\=10−220.22^{34} = 10^{-22} probability.

I checked a number of differences other than 0.3% and do find some dependence. The maximum probability found was 0.36, resulting in at most a 0.3634\=10−150.36^{34} = 10^{-15} chance of finding a sequence like this by chance. This is still 'zero' and also far too optimistic as the higher probability is found for just one of the (N, M) combinations. The authors also always measure 3 or more cells, showing that the probability-wise optimal p2\_2 = 0 solution is incorrect.

## Conclusion

Finding 35 independent measurements to show exactly a 0.3% difference is impossible to have happened by chance. On top of that, the comments above point out more of these coincidental sequences. That overview is also not complete, with e.g. the shHDAC6(24 h) column also showing extremely regular differences with its shTET2 (0 hr) neighbor.

In my opinion this data has been fabricated.

[![file](https://pubpeer.com/storage/image-1775804809820.png)](https://pubpeer.com/storage/image-1775804809820.png)

| γH2AX (n) | total (N) | (ratio) |  | γH2AX (m) | total (M) | (ratio) |
| --- | --- | --- | --- | --- | --- | --- |
| 9 | 2000 | 0.0045 |  | 3 | 2000 | 0.0015 |
| 6 | 1000 | 0.006 |  | 3 | 1000 | 0.003 |
| 9 | 1000 | 0.009 |  | 6 | 1000 | 0.006 |
| 3 | 250 | 0.012 |  | 9 | 1000 | 0.009 |
| 9 | 1000 | 0.009 |  | 30 | 5000 | 0.006 |
| 6 | 250 | 0.024 |  | 21 | 1000 | 0.021 |
| 26 | 1000 | 0.026 |  | 23 | 1000 | 0.023 |
| 7 | 250 | 0.028 |  | 50 | 2000 | 0.025 |
| 4 | 125 | 0.032 |  | 29 | 1000 | 0.029 |
| 34 | 1000 | 0.034 |  | 31 | 1000 | 0.031 |
| 65 | 2500 | 0.026 |  | 46 | 2000 | 0.023 |
| 3 | 100 | 0.03 |  | 27 | 1000 | 0.027 |
| 4 | 125 | 0.032 |  | 29 | 1000 | 0.029 |
| 34 | 1000 | 0.034 |  | 62 | 2000 | 0.031 |
| 5 | 200 | 0.025 |  | 11 | 500 | 0.022 |
| 23 | 1000 | 0.023 |  | 10 | 500 | 0.02 |
| 27 | 1000 | 0.027 |  | 6 | 250 | 0.024 |
| 7 | 250 | 0.028 |  | 5 | 200 | 0.025 |
| 26 | 1000 | 0.026 |  | 23 | 1000 | 0.023 |
| 167 | 5000 | 0.0334 |  | 38 | 1250 | 0.0304 |
| 33 | 1250 | 0.0264 |  | 234 | 10000 | 0.0234 |
| 86 | 2500 | 0.0344 |  | 157 | 5000 | 0.0314 |
| 76 | 2500 | 0.0304 |  | 274 | 10000 | 0.0274 |
| 106 | 2500 | 0.0424 |  | 394 | 10000 | 0.0394 |
| 56 | 2500 | 0.0224 |  | 97 | 5000 | 0.0194 |
| 66 | 2500 | 0.0264 |  | 117 | 5000 | 0.0234 |
| 106 | 2500 | 0.0424 |  | 197 | 5000 | 0.0394 |
| 23 | 1250 | 0.0184 |  | 77 | 5000 | 0.0154 |
| 22 | 1000 | 0.022 |  | 19 | 1000 | 0.019 |
| 7 | 250 | 0.028 |  | 5 | 200 | 0.025 |
| 7 | 200 | 0.035 |  | 16 | 500 | 0.032 |
| 38 | 1000 | 0.038 |  | 7 | 200 | 0.035 |
| 8 | 125 | 0.064 |  | 61 | 1000 | 0.061 |
| 54 | 1000 | 0.054 |  | 51 | 1000 | 0.051 |
| 8 | 200 | 0.04 |  | 37 | 1000 | 0.037 |
