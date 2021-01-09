//
// Created by xx on 2019/12/15.
//
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
/*
 * Bug is loop can not being break
 */
int main(void) {
    int no;
    srand(time(NULL));
    int ans = rand();
    printf("Random number is: %d", ans);
    printf("\n Please guess the number from 0 to  100: \n");
    while (no != ans) {
        scanf("Please input your number: %d ", &no);
        if (ans < no)
            printf("Your number is bigger! \n");
        else if (ans > no)
            printf("Your number is smaller! \n");
    };
    printf("Your number is right!!! \n");
    return 0;
}

