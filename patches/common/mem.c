/* memset/memcpy for patch code. There is no libc, but GCC may emit calls to
 * these for struct copies and zeroing loops even with -ffreestanding. */

#include <stddef.h>
#include <stdint.h>

void *memset(void *dst, int c, size_t n)
{
    uint8_t *d = dst;
    while (n--)
        *d++ = (uint8_t)c;
    return dst;
}

void *memcpy(void *restrict dst, const void *restrict src, size_t n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--)
        *d++ = *s++;
    return dst;
}
