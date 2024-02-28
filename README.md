# tmxparse

A Python 3.12+ library for parsing TMX files. Has support for specialization based on the type selected in-editor (e.g. allowing you to quickly and easily create custom object logic). It's in its very early stages so far, but it's getting there

## Basic usage
You can use tmxparse.BaseLoader to open a map file:

```python
>>> import tmxparser
>>> tmap = tmxparser.BaseLoader().load("map.tmx")
>>> tmap
<Map 'map.tmx' 56x42>
```

The module allows the map's structure to be easily traversed:

```python
>>> tmap.layers
[<Layer 52x46>, <Layer 52x46>, <ObjectGroup [<Object 'player' (type player)>, <Object None (type enemy)>]>, <Layer 52x46>, <ObjectGroup [<Object None (type warp)>, <Object None (type warp)>, <Object None (type warp)>, <Object None (type warp)>]>, <ImageLayer <Image 'overlay.png' (640x480)>>]
>>> tmap.tilewidth, tmap.tileheight
(32, 32)
>>> tmap.layers[0][10,15]
41
>>> tmap.tiles[tmap.layers[0][10,15]]
<Tile #41 (properties {'wall': True})>
>>> tmap.layers[2].objects[0].x
568.0
>>> tmap.layers[2].objects[0].y
448.0
>>> tmap.layers[2].objects[0].has_tile
True
>>> tmap.layers[2].objects[0].tile
<Tile #1249>
```

You can also iterate over the tiles of a `tmxparse.TileLayer`:

```python
>>> for x, y, tile in tmap.layers[0]:
...    print(x, y, tile)
...
0 0 <Tile #89 (properties {'wall': True})>
1 0 <Tile #89 (properties {'wall': True})>
2 0 <Tile #49 (properties {'wall': True})>
3 0 <Tile #49 (properties {'wall': True})>
4 0 <Tile #49 (properties {'wall': True})>
```

## Customizing
By inheriting from a BaseLoader, you can easily specialize any type for which the Tiled editor allows you to assign a custom class or type, such that the correct subclass is chosen:

```python
>>> class MyLoader(tmxparse.BaseLoader):
...     pass
...
>>> @MyLoader.register
... class MyObject(tmxparse.Object, base=True):
...     pass
...
>>> class Player(MyObject, tiled_class="player"):
...     def post_load(self):
...         print("My name is", self.name, "and I'm the player")
...
>>> class Enemy(MyObject, tiled_class="enemy"):
...     def post_load(self):
...         print("My name is", self.name, "and I'm an enemy")
...
>>> @MyLoader.register
... class MyImageLayer(tmxparse.ImageLayer, base=True):
...     pass
...
>>> class Overlay(MyImageLayer, tiled_class="overlay"):
...     def post_load(self):
...         print("I'm an overlay")
...
>>> MyLoader().load("map.tmx")
My name is player and I'm the player
My name is None and I'm the enemy
I'm an overlay
<Map 'map.tmx' 56x42>
```

## Pygame integration
The module has built-in support for Pygame under tmxparse.pg_compat. It introduces a `surface` property to Tile and Image, as well as automatically loads fonts for `tmxparse.Text` instances.

```python
>>> import tmxparse.pg_compat as tmx_pygame
>>> tmap = tmx_pygame.PygameLoader(convert_alpha=False).load("map.tmx")
>>> tmap.tiles[41].surface
<Surface(32x32x32, global_alpha=255)>
```
