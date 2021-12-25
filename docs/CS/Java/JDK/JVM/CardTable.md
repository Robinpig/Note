


// Mapping from address to card marking array entry
```cpp
CardValue* byte_for(const void* p) const {
  assert(_whole_heap.contains(p),
         "Attempt to access p = " PTR_FORMAT " out of bounds of "
         " card marking array's _whole_heap = [" PTR_FORMAT "," PTR_FORMAT ")",
         p2i(p), p2i(_whole_heap.start()), p2i(_whole_heap.end()));
  CardValue* result = &_byte_map_base[uintptr_t(p) >> _card_shift];
  assert(result >= _byte_map && result < _byte_map + _byte_map_size,
         "out of bounds accessor for card marking array");
  return result;
}
```


```cpp
class CardTable: public CHeapObj<mtGC> {
protected:
  // The declaration order of these const fields is important; see the
  // constructor before changing.
  const MemRegion _whole_heap;       // the region covered by the card table
  size_t          _guard_index;      // index of very last element in the card
                                     // table; it is set to a guard value
                                     // (last_card) and should never be modified
  size_t          _last_valid_index; // index of the last valid element
  const size_t    _page_size;        // page size used when mapping _byte_map
  size_t          _byte_map_size;    // in bytes
  CardValue*      _byte_map;         // the card marking array
  CardValue*      _byte_map_base;
  
}
```


Card marking array base (adjusted for heap low boundary)
This would be the 0th element of _byte_map, if the heap started at 0x0.
But since the heap starts at some higher address, this points to somewhere before the beginning of the actual _byte_map.
```cpp
  CardValue* byte_map_base() const { return _byte_map_base; }

```