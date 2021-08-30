##
memory

- used_memory
  - process memory
  - data memory
  - buffer memory
    - client buffer
      - client buffer for connections
      - slaves client connections
      - pub/sub connections  
    - copy buffer
    - AOF buffer
- fragmentation

mem_fragmentation_ratio usually 1.03

if > 1, is fragmentation
< 1, using swap

fragmentation by 

- usually using append setrange
- delete lots of expire keys

allocate memory by jemelloc
small: << 8byte
big : << 4KB
huge : << 4MB