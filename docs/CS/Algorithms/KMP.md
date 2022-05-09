## Introduction

Substring Search


## BF 

Brute-force substring search requires ~NM character compares to search for a pattern of length M in a text of length N, in the worst case.







## KMP

Temp array

Knuth-Morris-Pratt substring search accesses no more than M+N characters to search for a pattern of length M in a text of length N.

space complexity O(N)

```java
public class KMPSearch {
    public static void main(String[] args) {
        String str = "abcxabcdabcdabcy";
        String subString = "abcdabcy";
        KMPSearch ss = new KMPSearch();
        boolean result = ss.KMP(str.toCharArray(), subString.toCharArray());
        System.out.print(result);
    }

    public boolean KMP(char[] text, char[] pattern) {
        int[] lps = computeTemporaryArray(pattern);
        int i = 0;
        int j = 0;
        while (i < text.length && j < pattern.length) {
            if (text[i] == pattern[j]) {
                i++;
                j++;
            } else {
                if (j != 0) {
                    j = lps[j - 1]; // return the latest matched index
                } else {
                    i++;
                }
            }
        }
        return j == pattern.length;
    }

    /**
     * index, i
     * 1. if equals, lps[i] = index + 1, both index and i step next
     * 2. else 
     *      1. if index != 0, index = lps[index - 1]
     *      2. else lps[i] = 0, i step
     */
    private int[] computeTemporaryArray(char[] pattern) {
        int[] lps = new int[pattern.length];
        int index = 0;
        for (int i = 1; i < pattern.length; ) {
            if (pattern[i] == pattern[index]) {
                lps[i] = index + 1;
                index++;
                i++;
            } else {
                if (index != 0) {
                    index = lps[index - 1];
                } else {
                    lps[i] = 0;
                    i++;
                }
            }
        }
        return lps;
    }
}
```

## BM


## RK


