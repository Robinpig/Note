# Primitive Class
###类型
| 基本类型 | 包装器类型 | 大小 |
| :---: | :---: | :---: |
| boolean | Boolean | - |
| char | Character | 16-bits |
| byte | Byte | 8-bits |
| short | Short | 16-bits |
| int | Integer | 32-bits |
| long | Long | 64-bits |
| float | Float | 32-bits |
| double | Double | 64-bits |
| void | Void | - |
####Boolean
私有属性

    private final boolean value;

实现Cpmpare接口，重写compare方法

    public static int compare(boolean x, boolean y) {
        return (x == y) ? 0 : (x ? 1 : -1);
    }
构造器:可传入原始类型或String忽略大小写判断是否为true

     public static boolean parseBoolean(String s) {
            return ((s != null) && s.equalsIgnoreCase("true"));
        }

通过valueOf方法始终返回的是静态常量，即同一对象，减少开销

    public static Boolean valueOf(boolean b) {
        return (b ? TRUE : FALSE);
    }

重写了hashCode方法，实质调用静态方法返回1231或1237

    public static int hashCode(boolean value) {
            return value ? 1231 : 1237;
        }

1.8版本增加logicAnd\logicOr\logicXor方法
####Integer
属性值：

    @Native public static final int   MIN_VALUE = 0x80000000;
    @Native public static final int   MAX_VALUE = 0x7fffffff;
    //hashCode返回value
    private final int value;
    @Native public static final int SIZE = 32;
    //4bytes
    public static final int BYTES = SIZE / Byte.SIZE;
    final static char[] digits = {
            '0' , '1' , '2' , '3' , '4' , '5' ,
            '6' , '7' , '8' , '9' , 'a' , 'b' ,
            'c' , 'd' , 'e' , 'f' , 'g' , 'h' ,
            'i' , 'j' , 'k' , 'l' , 'm' , 'n' ,
            'o' , 'p' , 'q' , 'r' , 's' , 't' ,
            'u' , 'v' , 'w' , 'x' , 'y' , 'z'
        };
    



    public static int highestOneBit(int i) {
        // HD, Figure 3-1
        i |= (i >>  1);
        i |= (i >>  2);
        i |= (i >>  4);
        i |= (i >>  8);
        i |= (i >> 16);
        return i - (i >>> 1);
    }