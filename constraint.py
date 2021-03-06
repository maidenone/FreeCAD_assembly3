from collections import namedtuple
import FreeCAD, FreeCADGui, Part
from . import utils, gui
from .utils import objName,cstrlogger as logger, guilogger
from .proxy import ProxyType, PropertyInfo, propGet, propGetValue

import os
_iconPath = os.path.join(utils.iconPath,'constraints')

PointInfo = namedtuple('PointInfo', ('entity','params','vector'))
LineInfo = namedtuple('LineInfo', ('entity','p0','p1'))
NormalInfo = namedtuple('NormalInfo', ('entity','rot','params','p0','ln'))
PlaneInfo = namedtuple('PlaneInfo', ('entity','origin','normal'))
CircleInfo = namedtuple('CurcleInfo',('entity','radius','p0'))
ArcInfo = namedtuple('CurcleInfo',('entity','p1','p0','params'))

def _d(solver,partInfo,subname,shape,retAll=False):
    'return a handle of any supported element of a draft object'
    if not solver:
        if utils.isDraftObject(partInfo):
            return
        raise RuntimeError('Expects only elements from a draft wire or '
            'draft circle/arc')
    if subname.startswith('Vertex'):
        return _p(solver,partInfo,subname,shape,retAll)
    elif subname.startswith('Edge'):
        return _l(solver,partInfo,subname,shape,retAll)
    else:
        raise RuntimeError('Invalid element {} of object {}'.format(subname,
            partInfo.PartName))

def _prepareDraftCircle(solver,partInfo,requireArc=False):
    part = partInfo.Part
    shape = utils.getElementShape((part,'Edge1'),Part.Edge)
    func = _a if requireArc else _c
    return func(solver,partInfo,'Edge1',shape,retAll=True)

def _p(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed point derived from "shape"'
    if not solver:
        if not utils.hasCenter(shape):
            return 'a vertex or circular edge/face'
        if utils.isDraftWire(partInfo):
            if utils.draftWireVertex2PointIndex(partInfo,subname) is None:
                raise RuntimeError('Invalid draft wire vertex "{}" {}'.format(
                    subname,objName(partInfo)))
        return

    part = partInfo.Part
    key = subname+'.p'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
        return h if retAll else h.entity

    v = utils.getElementPos(shape)

    if utils.isDraftWire(part):
        nameTag = partInfo.PartName + '.' + key
        v = partInfo.Placement.multVec(v)
        params = []
        for n,val in (('.x',v.x),('.y',v.y),('.z',v.z)):
            system.NameTag = nameTag+n
            params.append(system.addParamV(val,group=partInfo.Group))
        system.NameTag = nameTag
        e = system.addPoint3d(*params)
        h = PointInfo(entity=e,params=params,vector=v)
        system.log('{}: add draft point {}'.format(key,h))

        if system.sketchPlane and not solver.isFixedElement(part,subname):
            system.NameTag = nameTag + '.i'
            e2 = system.addPointInPlane(e,system.sketchPlane.entity,
                group=partInfo.Group)
            system.log('{}: add draft point in plane {},{}'.format(
                partInfo.PartName,e2,system.sketchPlane.entity))

    elif utils.isDraftCircle(part):
        requireArc = subname=='Vertex2'
        e = _prepareDraftCircle(solver,partInfo,requireArc)
        if requireArc or subname=='Vertex1':
            h = PointInfo(entity=e.p0,params=partInfo.Params,vector=v)
        elif subname=='Edge1':
            # center point
            h = partInfo.Workplane.origin
        else:
            raise RuntimeError('Invalid draft circle subname {} of '
                    '{}'.format(subname,partInfo.PartName))
        system.log('{}: add circle point {}'.format(key,h))

    else:
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag
        e = system.addPoint3dV(*v)
        system.NameTag = nameTag + 't'
        h = system.addTransform(e,*partInfo.Params,group=partInfo.Group)
        h = PointInfo(entity=h, params=partInfo.Params,vector=v)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))

    partInfo.EntityMap[key] = h
    return h if retAll else h.entity

def _n(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed normal quaterion derived from shape'
    if not solver:
        if not utils.isPlanar(shape) and not utils.isCylindricalPlane(shape):
            return 'an edge or face with a planar or cylindrical surface'
        if utils.isDraftWire(partInfo):
            logger.warn('Use draft wire {} for normal. Draft wire placement'
                ' is not transformable'.format(partInfo.PartName))
        return

    key = subname+'.n'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        if utils.isDraftCircle(partInfo.Part):
            _prepareDraftCircle(solver,partInfo)

        rot = utils.getElementRotation(shape)
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag
        e = system.addNormal3dV(*utils.getNormal(rot))
        system.NameTag += 't'
        nz = system.addTransform(e,*partInfo.Params,group=partInfo.Group)

        p0 = _p(solver,partInfo,subname,shape,True)
        v = rot.inverted().multVec(p0.vector)
        v.z += 1
        v = rot.multVec(v)
        system.NameTag = nameTag + 'p1'
        e = system.addPoint3dV(*v)
        system.NameTag += 't'
        p1 = system.addTransform(e,*partInfo.Params,group=partInfo.Group)

        system.NameTag = nameTag + 'l'
        ln = system.addLineSegment(p0.entity,p1,group=partInfo.Group)

        h = NormalInfo(entity=nz,rot=rot,
                params=partInfo.Params, p0=p0.entity, ln=ln)

        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h.entity

def _l(solver,partInfo,subname,shape,retAll=False):
    'return a pair of handle of the end points of an edge in "shape"'
    if not solver:
        if not utils.isLinearEdge(shape):
            return 'a linear edge'

        if not utils.isDraftWire(partInfo):
            return
        vname1,vname2 = utils.edge2VertexIndex(partInfo,subname)
        if not vname1:
            raise RuntimeError('Invalid draft subname {} or {}'.format(
                subname,objName(partInfo)))
        v = shape.Edge1.Vertexes
        ret = _p(solver,partInfo,vname1,v[0])
        if ret:
            return ret
        return _p(solver,partInfo,vname2,v[1])

    part = partInfo.Part
    key = subname+'.l'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        nameTag = partInfo.PartName + '.' + key
        if utils.isDraftWire(part):
            v = shape.Edge1.Vertexes
            vname1,vname2 = utils.edge2VertexIndex(part,subname)
            if not vname1:
                raise RuntimeError('Invalid draft subname {} or {}'.format(
                    subname,partInfo.PartName))
            tp0 = _p(solver,partInfo,vname1,v[0])
            tp1 = _p(solver,partInfo,vname2,v[1])
        else:
            v = shape.Edge1.Vertexes
            system.NameTag = nameTag + 'p0'
            p0 = system.addPoint3dV(*v[0].Point)
            system.NameTag = nameTag + 'p0t'
            tp0 = system.addTransform(p0,*partInfo.Params,group=partInfo.Group)
            system.NameTag = nameTag + 'p1'
            p1 = system.addPoint3dV(*v[-1].Point)
            system.NameTag = nameTag + 'p1t'
            tp1 = system.addTransform(p1,*partInfo.Params,group=partInfo.Group)

        system.NameTag = nameTag
        h = system.addLineSegment(tp0,tp1,group=partInfo.Group)
        h = LineInfo(entity=h,p0=tp0,p1=tp1)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h

    return h if retAll else h.entity

def _la(solver,partInfo,subname,shape,retAll=False):
   _ = retAll
   return _l(solver,partInfo,subname,shape,True)

def _dl(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a draft wire'
    if not solver:
        if utils.isDraftWire(partInfo):
            return
        raise RuntimeError('Requires a non-subdivided draft wire')
    return _l(solver,partInfo,subname,shape,retAll)

def _ln(solver,partInfo,subname,shape,retAll=False):
    'return a handle for either a line or a normal depends on the shape'
    if not solver:
        if utils.isLinearEdge(shape) or \
           utils.isPlanar(shape) or \
           utils.isCylindricalPlane(shape):
            return
        return 'a linear edge or edge/face with planar or cylindrical surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,subname,shape,retAll)
    return _n(solver,partInfo,subname,shape,retAll)

def _lna(solver,partInfo,subname,shape,retAll=False):
    _ = retAll
    return _ln(solver,partInfo,subname,shape,True)

def _lw(solver,partInfo,subname,shape,retAll=False):
    'return a handle for either a line or a plane depending on the shape'
    _ = retAll
    if not solver:
        if utils.isLinearEdge(shape) or utils.isPlanar(shape):
            return
        return 'a linear edge or edge/face with planar surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,subname,shape,False)
    return _wa(solver,partInfo,subname,shape)

def _w(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed plane/workplane from "shape"'
    if not solver:
        if utils.isPlanar(shape):
            return
        return 'an edge/face with a planar surface'

    key = subname+'.w'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        p = _p(solver,partInfo,subname,shape,True)
        n = _n(solver,partInfo,subname,shape,True)
        system.NameTag = partInfo.PartName + '.' + key
        w = system.addWorkplane(p.entity,n.entity,group=partInfo.Group)
        h = PlaneInfo(entity=w,origin=p,normal=n)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
    return h if retAll else h.entity

def _wa(solver,partInfo,subname,shape,retAll=False):
    _ = retAll
    return _w(solver,partInfo,subname,shape,True)

def _c(solver,partInfo,subname,shape,requireArc=False,retAll=False):
    'return a handle of a transformed circle/arc derived from "shape"'
    if not solver:
        r = utils.getElementCircular(shape)
        if r:
            if requireArc and not isinstance(r,tuple):
                return 'an arc edge'
            return
        return 'a cicular edge'
    if requireArc:
        key = subname+'.a'
    else:
        key = subname+'.c'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
        return h if retAll else h.entity

    g = partInfo.Group
    nameTag = partInfo.PartName + '.' + key

    if utils.isDraftCircle(partInfo.Part):
        part = partInfo.Part
        pln = partInfo.Workplane

        if system.sketchPlane and not solver.isFixedElement(part,subname):
            system.NameTag = nameTag + '.o'
            e1 = system.addSameOrientation(pln.normal.entity,
                    system.sketchPlane.normal.entity, group=g)
            system.NameTag = nameTag + '.i'
            e2 = system.addPointInPlane(
                    pln.origin.entity, system.sketchPlane.entity, group=g)
            system.log('{}: fix draft circle in plane {},{}'.format(
                partInfo.PartName,e1,e2))

        if part.FirstAngle == part.LastAngle:
            if requireArc:
                raise RuntimeError('expecting an arc from {}'.format(
                    partInfo.PartName))
            system.NameTag = nameTag + '.r'
            r = system.addParamV(part.Radius.Value,group=g)
            system.NameTag = nameTag + '.p0'
            p0 = system.addPoint2d(pln.entity,r,solver.v0,group=g)
            system.NameTag = nameTag
            e = system.addCircle(pln.origin.entity, pln.normal.entity,
                                 system.addDistance(r), group=g)
            h = CircleInfo(entity=e,radius=r,p0=p0)
            system.log('{}: add draft circle {}, {}'.format(key,h,g))
        else:
            system.NameTag = nameTag + '.c'
            center = system.addPoint2d(pln.entity,solver.v0,solver.v0,group=g)
            params = []
            points = []
            v = shape.Vertexes
            for i in 0,1:
                for n,val in ('.x{}',v[i].Point.x),('.y{}',v[i].Point.y):
                    system.NameTag = nameTag+n.format(i)
                    params.append(system.addParamV(val,group=g))
                system.NameTag = nameTag + '.p{}'.format(i)
                pt = system.addPoint2d(pln.entity,*params[-2:],group=g)
                points.append(pt)
            system.NameTag = nameTag
            e = system.addArcOfCircle(pln.entity,center,*points,group=g)
            h = ArcInfo(entity=e,p1=points[1],p0=points[0],params=params)
            system.log('{}: add draft arc {}, {}'.format(key,h,g))

            # exhaust all possible keys from a draft circle to save
            # recomputation
            sub = subname + '.c' if requireArc else '.a'
            partInfo.EntityMap[sub] = h
    else:
        pln = _w(solver,partInfo,subname,shape,True)
        r = utils.getElementCircular(shape)
        if not r:
            raise RuntimeError('shape is not cicular')
        system.NameTag = nameTag + '.r'
        hr = system.addDistanceV(r)
        if requireArc or isinstance(r,(list,tuple)):
            l = _l(solver,partInfo,subname,shape,True)
            system.NameTag = nameTag
            h = system.addArcOfCircle(
                    pln.entity, pln.origin.entity, l.p0, l.p1, group=g)
            h = ArcInfo(entity=h,p1=l.p1,p0=l.p0,params=None)
        else:
            system.NameTag = nameTag
            h = system.addCircle(
                    pln.origin.entity, pln.normal.entity, hr, group=g)
            h = CircleInfo(entity=h,radius=hr,p0=None)
        system.log('{}: {},{}'.format(key,h,g))

    partInfo.EntityMap[key] = h

    return h if retAll else h.entity

def _dc(solver,partInfo,subname,shape,requireArc=False,retAll=False):
    'return a handle of a draft circle'
    if not solver:
        if utils.isDraftCircle(partInfo):
            return
        raise RuntimeError('Requires a draft circle')
    return _c(solver,partInfo,subname,shape,requireArc,retAll)

def _a(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed arc derived from "shape"'
    return _c(solver,partInfo,subname,shape,True,retAll)


class ConstraintCommand:
    _menuGroupName = ''

    def __init__(self,tp):
        self.tp = tp
        self._id = 100 + tp._id
        self._active = None

    @property
    def _toolbarName(self):
        return self.tp._toolbarName

    def workbenchActivated(self):
        self._active = None

    def workbenchDeactivated(self):
        pass

    def getContextMenuName(self):
        pass

    def getName(self):
        return 'asm3Add'+self.tp.getName()

    def GetResources(self):
        return self.tp.GetResources()

    def Activated(self):
        from .assembly import AsmConstraint
        guilogger.report('constraint "{}" command exception'.format(
            self.tp.getName()), AsmConstraint.make,self.tp._id)

    def IsActive(self):
        if not FreeCAD.ActiveDocument:
            return False
        if self._active is None:
            self.checkActive()
        return self._active

    def checkActive(self):
        from .assembly import AsmConstraint
        if guilogger.catchTrace('selection "{}" exception'.format(
                self.tp.getName()), AsmConstraint.getSelection, self.tp._id):
            self._active = True
        else:
            self._active = False

    def onClearSelection(self):
        self._active = False

class Constraint(ProxyType):
    'constraint meta class'

    _typeID = '_ConstraintType'
    _typeEnum = 'ConstraintType'
    _disabled = 'Disabled'

    @classmethod
    def register(mcs,cls):
        super(Constraint,mcs).register(cls)
        if cls._id>=0 and cls._iconName is not Base._iconName:
            try:
                gui.AsmCmdManager.register(ConstraintCommand(cls))
            except Exception:
                logger.error('failed to register {}'.format(cls.getName()))
                raise

    @classmethod
    def attach(mcs,obj,checkType=True):
        if checkType:
            if not mcs._disabled in obj.PropertiesList:
                obj.addProperty("App::PropertyBool",mcs._disabled,"Base",'')
        return super(Constraint,mcs).attach(obj,checkType)

    @classmethod
    def onChanged(mcs,obj,prop):
        if prop == mcs._disabled:
            obj.ViewObject.signalChangeIcon()
        if super(Constraint,mcs).onChanged(obj,prop):
            try:
                if obj.Name==obj.Label or \
                   mcs.getType(utils.getLabel(obj)):
                    obj.Label = mcs.getTypeName(obj)
            except Exception as e:
                logger.debug('auto constraint label failed: {}'.format(e))

    @classmethod
    def isDisabled(mcs,obj):
        return getattr(obj,mcs._disabled,False)

    @classmethod
    def check(mcs,tp,elements,checkCount=False):
        mcs.getType(tp).check(elements,checkCount)

    @classmethod
    def prepare(mcs,obj,solver):
        return mcs.getProxy(obj).prepare(obj,solver)

    @classmethod
    def getFixedParts(mcs,solver,cstrs,parts):
        firstInfo = None
        ret = set()

        from .assembly import isTypeOf, AsmWorkPlane
        for obj in parts:
            if not hasattr(obj,'Placement'):
                ret.add(obj)
            elif isTypeOf(obj,AsmWorkPlane) and getattr(obj,'Fixed',False):
                ret.add(obj)
        found = len(ret)

        for obj in cstrs:
            cstr = mcs.getProxy(obj)
            if cstr.hasFixedPart(obj):
                found = True
                for info in cstr.getFixedParts(solver,obj):
                    logger.debug('fixed part ' + info.PartName)
                    ret.add(info.Part)

            if not found and not firstInfo:
                elements = obj.Proxy.getElements()
                if elements:
                    firstInfo = elements[0].Proxy.getInfo()

        if not found:
            if not firstInfo or not solver:
                return ret
            if utils.isDraftObject(firstInfo.Part):
                Locked.lockElement(firstInfo,solver)
                logger.debug('lock first draft object {}'.format(
                    firstInfo.PartName))
                solver.getPartInfo(firstInfo,True,solver.group)
            else:
                logger.debug('lock first part {}'.format(firstInfo.PartName))
                ret.add(firstInfo.Part)
        return ret

    @classmethod
    def getFixedTransform(mcs,cstrs):
        firstPart = None
        found = False
        ret = {}
        for obj in cstrs:
            cstr = mcs.getProxy(obj)
            if cstr.hasFixedPart(obj):
                for info in cstr.getFixedTransform(obj):
                    found = True
                    ret[info.Part] = info

            if not found and not firstPart:
                elements = obj.Proxy.getElements()
                if elements:
                    info = elements[0].Proxy.getInfo()
                    firstPart = info.Part
        if not found and firstPart and not utils.isDraftObject(firstPart):
            ret[firstPart] = False
        return ret

    @classmethod
    def getIcon(mcs,obj):
        cstr = mcs.getProxy(obj)
        if cstr:
            return cstr.getIcon(obj)

    @classmethod
    def init(mcs,obj):
        cstr = mcs.getProxy(obj)
        if cstr:
            cstr.init(obj)


def _makeProp(name,tp,doc='',getter=propGet,internal=False,default=None):
    return PropertyInfo(Constraint,name,tp,doc,getter=getter,duplicate=True,
            group='Constraint',internal=internal,default=default).Key

_makeProp('Distance','App::PropertyDistance',getter=propGetValue)
_makeProp('Length','App::PropertyDistance',getter=propGetValue,default=5.0)
_makeProp('Offset','App::PropertyDistance',getter=propGetValue)
_makeProp('OffsetX','App::PropertyDistance',getter=propGetValue)
_makeProp('OffsetY','App::PropertyDistance',getter=propGetValue)
_makeProp('Cascade','App::PropertyBool',internal=True)
_makeProp('Angle','App::PropertyAngle',getter=propGetValue)

_AngleProps = [
_makeProp('LockAngle','App::PropertyBool',
        doc='Enforce an angle offset defined as yaw-pitch-roll angle of the\n'
            'second plane performed in the order of x-y-z'),
_makeProp('Angle','App::PropertyAngle',getter=propGetValue,
        doc='The rotation angle of the second plane about its z-axis.\n'
            'You need to enable LockAngle for this to take effect.'),
_makeProp('AnglePitch','App::PropertyAngle',getter=propGetValue,
        doc='Rotation angle of the second plane about its y-axis.\n'
            'You need to enable LockAngle for this to take effect.'),
_makeProp('AngleRoll','App::PropertyAngle',getter=propGetValue,
        doc='Rotation angle of the second plane about its x-axis\n'
            'You need to enable LockAngle for this to take effect.'),
]

_makeProp('Ratio','App::PropertyFloat',default=1.0)
_makeProp('Difference','App::PropertyFloat')
_makeProp('Diameter','App::PropertyDistance',getter=propGetValue,default=10.0)
_makeProp('Radius','App::PropertyDistance',getter=propGetValue,default=5.0)
_makeProp('Supplement','App::PropertyBool',
        'If True, then the angle is calculated as 180-angle')
_makeProp('AtEnd','App::PropertyBool',
        'If True, then tangent at the end point, or else at the start point')

_ordinal = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th')

def cstrName(obj):
    return '{}<{}>'.format(objName(obj),Constraint.getTypeName(obj))


class Base(object):
    __metaclass__ = Constraint
    _id = -1
    _entityDef = ()
    _workplane = False
    _props = []
    _toolbarName = 'Assembly3 Constraints'
    _iconName = 'Assembly_ConstraintGeneral.svg'
    _menuText = 'Create "{}" constraint'

    def __init__(self,_obj):
        pass

    @classmethod
    def init(cls,_obj):
        pass

    @classmethod
    def getPropertyInfoList(cls):
        return cls._props

    @classmethod
    def constraintFunc(cls,obj,solver):
        try:
            return getattr(solver.system,'add'+cls.getName())
        except AttributeError:
            logger.warn('{} not supported in solver "{}"'.format(
                cstrName(obj),solver.getName()))

    @classmethod
    def getEntityDef(cls,elements,checkCount,obj=None):
        entities = cls._entityDef
        if len(elements) == len(entities):
            return entities
        if cls._workplane and len(elements)==len(entities)+1:
            return list(entities) + [_w]
        if not checkCount and len(elements)<len(entities):
            return entities[:len(elements)]
        if not obj:
            name = cls.getName()
        else:
            name += cstrName(obj)
        if len(elements)<len(entities):
            msg = entities[len(elements)](None,None,None,None)
            raise RuntimeError('Constraint "{}" requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[len(elements)], msg))
        raise RuntimeError('Constraint {} has too many elements, expecting '
            'only {}'.format(name,len(entities)))

    @classmethod
    def check(cls,elements,checkCount=False):
        entities = cls.getEntityDef(elements,checkCount)
        for i,e in enumerate(entities):
            info = elements[i]
            msg = e(None,info.Part,info.Subname,info.Shape)
            if not msg:
                continue
            if i == len(cls._entityDef):
                raise RuntimeError('Constraint "{}" requires an optional {} '
                    'element to be a planar face for defining a '
                    'workplane'.format(cls.getName(), _ordinal[i], msg))
            raise RuntimeError('Constraint "{}" requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[i], msg))

    @classmethod
    def getIcon(cls,obj):
        return utils.getIcon(cls,Constraint.isDisabled(obj),_iconPath)

    @classmethod
    def getEntities(cls,obj,solver,retAll=False):
        '''maps fcad element shape to entities'''
        elements = obj.Proxy.getElements()
        entities = cls.getEntityDef(elements,True,obj)
        ret = []
        for e,o in zip(entities,elements):
            info = o.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            ret.append(e(solver,partInfo,info.Subname,info.Shape,retAll=retAll))

        if cls._workplane and len(elements)==len(cls._entityDef):
            if solver.system.sketchPlane:
                ret.append(solver.system.sketchPlane.entity)
            elif int(cls._workplane)>1:
                raise RuntimeError('Constraint "{}" requires a sketch plane '
                    'or a {} element to define a projection plane'.format(
                    cstrName(obj), _ordinal[len(elements)]))

        solver.system.log('{} entities: {}'.format(cstrName(obj),ret))
        return ret

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver)
        if func:
            params = cls.getPropertyValues(obj) + cls.getEntities(obj,solver)
            ret = func(*params,group=solver.group)
            solver.system.log('{}: {}'.format(cstrName(obj),ret))
            return ret
        else:
            logger.warn('{} no constraint func'.format(cstrName(obj)))

    @classmethod
    def hasFixedPart(cls,_obj):
        return False

    @classmethod
    def getMenuText(cls):
        return cls._menuText.format(cls.getName())

    @classmethod
    def getToolTip(cls):
        tooltip = getattr(cls,'_tooltip',None)
        if not tooltip:
            return cls.getMenuText()
        return tooltip.format(cls.getName())

    @classmethod
    def GetResources(cls):
        return {'Pixmap':utils.addIconToFCAD(cls._iconName,_iconPath),
                'MenuText':cls.getMenuText(),
                'ToolTip':cls.getToolTip()}


class Locked(Base):
    _id = 0
    _iconName = 'Assembly_ConstraintLock.svg'
    _tooltip = 'Add a "{}" constraint to fix part(s)'

    @classmethod
    def getFixedParts(cls,_solver,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not utils.isVertex(info.Shape) and \
               not utils.isLinearEdge(info.Shape) and \
               not utils.isDraftCircle(info.Part):
                ret.append(info)
        return ret

    Info = namedtuple('AsmCstrTransformInfo', ('Part', 'Shape'))

    @classmethod
    def getFixedTransform(cls,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if utils.isDraftObject(info.Part):
                continue
            shape = None
            if utils.isVertex(info.Shape) or \
               utils.isLinearEdge(info.Shape):
                shape = info.Shape
            ret.append(cls.Info(Part=info.Part,Shape=shape))
        return ret

    @classmethod
    def hasFixedPart(cls,obj):
        return len(obj.Proxy.getElements())>0

    @classmethod
    def lockElement(cls,info,solver):
        ret = []
        system = solver.system

        isVertex = utils.isVertex(info.Shape)
        if solver.isFixedElement(info.Part,info.Subname):
            return ret

        if not isVertex and utils.isDraftCircle(info.Part):
            if solver.sketchPlane:
                _c(solver,solver.getPartInfo(info),info.Subname,info.Shape)
            else:
                solver.getPartInfo(info,True,solver.group)
            solver.addFixedElement(info.Part,info.Subname)
            return ret

        if not isVertex and not utils.isLinearEdge(info.Shape):
            return ret

        partInfo = solver.getPartInfo(info)

        fixPoint = False
        if isVertex:
            names = [info.Subname]
            if utils.isDraftCircle(info.Part):
                _c(solver,partInfo,'Edge1',info.Shape)
                solver.addFixedElement(info.Part,'Edge1')
        elif utils.isDraftWire(info.Part):
            fixPoint = True
            names = utils.edge2VertexIndex(info.Part,info.Subname)
        else:
            names = [info.Subname+'.fp0', info.Subname+'.fp1']

        nameTag = partInfo.PartName + '.' + info.Subname

        for i,v in enumerate(info.Shape.Vertexes):
            surfix = '.fp{}'.format(i)
            system.NameTag = nameTag + surfix

            # Create an entity for the transformed constant point
            e1 = system.addPoint3dV(*info.Placement.multVec(v.Point))

            # Get the entity for the point expressed in variable parameters
            e2 = _p(solver,partInfo,names[i],v)
            solver.addFixedElement(info.Part,names[i])

            if i==0 or fixPoint:
                # We are fixing a vertex, or a linear edge. Either way, we
                # shall add a point coincidence constraint here.
                e0 = e1
                system.NameTag = nameTag + surfix
                if system.sketchPlane and utils.isDraftObject(info.Part):
                    w = system.sketchPlane.entity
                else:
                    w = 0
                e = system.addPointsCoincident(e1,e2,w,group=solver.group)
                system.log('{}: fix point {},{},{}'.format(
                    info.PartName,e,e1,e2))
            else:
                # The second point, so we are fixing a linear edge. We can't
                # add a second coincidence constraint, which will cause
                # over-constraint. We constraint the second point to be on
                # the line defined by the linear edge.
                #
                # First, get an entity of the transformed constant line
                system.NameTag = nameTag + '.fl'
                l = system.addLineSegment(e0,e1)
                system.NameTag = nameTag
                # Now, constraint the second variable point to the line
                e = system.addPointOnLine(e2,l,group=solver.group)
                system.log('{}: fix line {},{}'.format(info.PartName,e,l))

            ret.append(e)

        return ret

    @classmethod
    def prepare(cls,obj,solver):
        ret = []
        for element in obj.Proxy.getElements():
            ret += cls.lockElement(element.Proxy.getInfo(),solver)
        return ret

    @classmethod
    def check(cls,elements,_checkCount=False):
        if not all([utils.isElement(info.Shape) for info in elements]):
            raise RuntimeError('Constraint "{}" requires all children to be '
                    'of element (Vertex, Edge or Face)'.format(cls.getName()))


class BaseMulti(Base):
    _id = -1
    _entityDef = (_wa,)

    @classmethod
    def check(cls,elements,checkCount=False):
        if checkCount and len(elements)<2:
            raise RuntimeError('Constraint "{}" requires at least two '
                'elements'.format(cls.getName()))
        for info in elements:
            msg = cls._entityDef[0](None,info.Part,info.Subname,info.Shape)
            if msg:
                raise RuntimeError('Constraint "{}" requires all the element '
                    'to be of {}'.format(cls.getName()))
        return

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver);
        if not func:
            logger.warn('{} no constraint func'.format(cstrName(obj)))
            return
        parts = set()
        ref = None
        elements = []
        props = cls.getPropertyValues(obj)

        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if info.Part in parts:
                logger.warn('{} skip duplicate parts {}'.format(
                    cstrName(obj),info.PartName))
                continue
            parts.add(info.Part)
            if solver.isFixedPart(info.Part):
                if ref:
                    logger.warn('{} skip more than one fixed part {}'.format(
                        cstrName(obj),info.PartName))
                    continue
                ref = info
                elements.insert(0,e)
            else:
                elements.append(e)
        if len(elements)<=1:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))
            return
        e0 = None
        ret = []
        firstInfo = None
        for e in elements:
            info = e.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            if not e0:
                e0 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
                firstInfo = partInfo
            else:
                e = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
                params = props + [e0,e]
                solver.system.checkRedundancy(obj,firstInfo,partInfo)
                h = func(*params,group=solver.group)
                if isinstance(h,(list,tuple)):
                    ret += list(h)
                else:
                    ret.append(h)
        return ret


class BaseCascade(BaseMulti):
    @classmethod
    def prepare(cls,obj,solver):
        if not getattr(obj,'Cascade',True):
            return super(BaseCascade,cls).prepare(obj,solver)
        func = cls.constraintFunc(obj,solver);
        if not func:
            logger.warn('{} no constraint func'.format(cstrName(obj)))
            return
        props = cls.getPropertyValues(obj)
        prev = None
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not prev or prev.Part==info.Part:
                prev = info
                continue
            prevInfo = solver.getPartInfo(prev)
            e1 = cls._entityDef[0](solver,prevInfo,prev.Subname,prev.Shape)
            partInfo = solver.getPartInfo(info)
            e2 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            prev = info
            if solver.isFixedPart(info.Part):
                params = props + [e1,e2]
            else:
                params = props + [e2,e1]
            solver.system.checkRedendancy(obj,prevInfo,partInfo)
            h = func(*params,group=solver.group)
            if isinstance(h,(list,tuple)):
                ret += list(h)
            else:
                ret.append(h)

        if not ret:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))
        return ret


class PlaneCoincident(BaseCascade):
    _id = 35
    _iconName = 'Assembly_ConstraintCoincidence.svg'
    _props = ['Cascade','Offset','OffsetX','OffsetY'] + _AngleProps
    _tooltip = \
        'Add a "{}" constraint to conincide planes of two or more parts.\n'\
        'The planes are coincided at their centers with an optional distance.'

class PlaneAlignment(BaseCascade):
    _id = 37
    _iconName = 'Assembly_ConstraintAlignment.svg'
    _props = ['Cascade','Offset'] + _AngleProps
    _tooltip = 'Add a "{}" constraint to rotate planes of two or more parts\n'\
               'into the same orientation'


class AxialAlignment(BaseMulti):
    _id = 36
    _entityDef = (_lna,)
    _iconName = 'Assembly_ConstraintAxial.svg'
    _props = _AngleProps
    _tooltip = 'Add a "{}" constraint to align planes of two or more parts.\n'\
        'The planes are aligned at the direction of their surface normal axis.'


class SameOrientation(BaseMulti):
    _id = 2
    _entityDef = (_n,)
    _iconName = 'Assembly_ConstraintOrientation.svg'
    _tooltip = 'Add a "{}" constraint to align planes of two or more parts.\n'\
        'The planes are aligned to have the same orientation (i.e. rotation)'


class MultiParallel(BaseMulti):
    _id = 291
    _entityDef = (_lw,)
    _iconName = 'Assembly_ConstraintMultiParallel.svg'
    _props = _AngleProps
    _tooltip = 'Add a "{}" constraint to make planes ormal or linear edges\n'\
        'of two or more parts parallel.'


class Base2(Base):
    _id = -1
    _toolbarName = 'Assembly3 Constraints2'


class Angle(Base2):
    _id = 27
    _entityDef = (_ln,_ln)
    _workplane = True
    _props = ["Angle","Supplement"]
    _iconName = 'Assembly_ConstraintAngle.svg'
    _tooltip = 'Add a "{}" constraint to set the angle of planes or linear\n'\
               'edges of two parts.'

    @classmethod
    def init(cls,obj):
        shapes = [ info.Shape for info in obj.Proxy.getElementsInfo() ]
        obj.Angle = utils.getElementsAngle(shapes[0],shapes[1])


class Perpendicular(Base2):
    _id = 28
    _entityDef = (_lw,_lw)
    _workplane = True
    _iconName = 'Assembly_ConstraintPerpendicular.svg'
    _tooltip = 'Add a "{}" constraint to make planes or linear edges of two\n'\
               'parts perpendicular.'

    @classmethod
    def prepare(cls,obj,solver):
        system = solver.system
        params = cls.getEntities(obj,solver)
        e1,e2 = params[0],params[1]
        isPlane = isinstance(e1,list),isinstance(e2,list)
        if all(isPlane):
            ret = system.addPerpendicular(e1[2],e2[2],group=solver.group)
        elif not any(isPlane):
            ret = system.addPerpendicular(e1,e2,group=solver.group)
        elif isPlane[0]:
            ret = system.addParallel(e1[2],e2,group=solver.group)
        else:
            ret = system.addParallel(e1,e2[2],group=solver.group)
        return ret


class Parallel(Base2):
    _id = -1
    _entityDef = (_ln,_ln)
    _workplane = True
    _iconName = 'Assembly_ConstraintParallel.svg'
    _tooltip = 'Add a "{}" constraint to make planes or linear edges of two\n'\
               'parts parallel.'


class PointsCoincident(Base2):
    _id = 1
    _entityDef = (_p,_p)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointsCoincident.svg'
    _tooltip = 'Add a "{}" constraint to conincide two points.'


class PointInPlane(Base2):
    _id = 3
    _entityDef = (_p,_w)
    _iconName = 'Assembly_ConstraintPointInPlane.svg'
    _tooltip = 'Add a "{}" to constrain a point inside a plane.'


class PointOnLine(Base2):
    _id = 4
    _entityDef = (_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointOnLine.svg'
    _tooltip = 'Add a "{}" to constrain a point on to a line.'


class PointsDistance(Base2):
    _id = 5
    _entityDef = (_p,_p)
    _workplane = True
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointsDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points.'

    @classmethod
    def init(cls,obj):
        points = [ info.Placement.multVec(info.Shape.Vertex1.Point)
                   for info in obj.Proxy.getElementsInfo() ]
        obj.Distance = points[0].distanceToPoint(points[1])


class PointsProjectDistance(Base2):
    _id = 6
    _entityDef = (_p,_p,_l)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointsProjectDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points\n' \
               'projected on a line.'


class PointPlaneDistance(Base2):
    _id = 7
    _entityDef = (_p,_w)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointPlaneDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a plane'


class PointLineDistance(Base2):
    _id = 8
    _entityDef = (_p,_l)
    _workplane = True
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a line'


class EqualPointLineDistance(Base2):
    _id = 13
    _entityDef = (_p,_l,_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n'\
             'line to be the same as the distance between another point\n'\
             'and line.'


class EqualAngle(Base2):
    _id = 14
    _entityDef = (_ln,_ln,_ln,_ln)
    _workplane = True
    _props = ["Supplement"]
    _iconName = 'Assembly_ConstraintEqualAngle.svg'
    _tooltip='Add a "{}" to equate the angles between two lines or normals.'


class Symmetric(Base2):
    _id = 16
    _entityDef = (_p,_p,_w)
    _iconName = 'Assembly_ConstraintSymmetric.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a plane.'


class SymmetricHorizontal(Base2):
    _id = 17
    _entityDef = (_p,_p)
    _workplane = 2


class SymmetricVertical(Base2):
    _id = 18
    _entityDef = (_p,_p)
    _workplane = 2


class SymmetricLine(Base2):
    _id = 19
    _entityDef = (_p,_p,_l)
    _workplane = 2
    _iconName = 'Assembly_ConstraintSymmetricLine.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a line.'


class PointsHorizontal(Base2):
    _id = 21
    _entityDef = (_p,_p)
    _workplane = 2
    _iconName = 'Assembly_ConstraintPointsHorizontal.svg'
    _tooltip='Add a "{}" constraint to make two points horizontal with each\n'\
             'other when projected onto a plane.'


class PointsVertical(Base2):
    _id = 22
    _entityDef = (_p,_p)
    _workplane = 2
    _iconName = 'Assembly_ConstraintPointsVertical.svg'
    _tooltip='Add a "{}" constraint to make two points vertical with each\n'\
             'other when projected onto a plane.'


class LineHorizontal(Base2):
    _id = 23
    _entityDef = (_l,)
    _workplane = 2
    _iconName = 'Assembly_ConstraintLineHorizontal.svg'
    _tooltip='Add a "{}" constraint to make a line segment horizontal when\n'\
             'projected onto a plane.'


class LineVertical(Base2):
    _id = 24
    _entityDef = (_l,)
    _workplane = 2
    _iconName = 'Assembly_ConstraintLineVertical.svg'
    _tooltip='Add a "{}" constraint to make a line segment vertical when\n'\
             'projected onto a plane.'

class PointOnCircle(Base2):
    _id = 26
    _entityDef = (_p,_c)
    _iconName = 'Assembly_ConstraintPointOnCircle.svg'
    _tooltip='Add a "{}" to constrain a point on to a clyndrical plane\n' \
             'defined by a cricle.'


class ArcLineTangent(Base2):
    _id = 30
    _entityDef = (_a,_l)
    _props = ["AtEnd"]
    _iconName = 'Assembly_ConstraintArcLineTangent.svg'
    _tooltip='Add a "{}" constraint to make a line tangent to an arc\n'\
             'at the start or end point of the arc.'

class Colinear(Base2):
    _id = 39
    _entityDef = (_lna, _lna)
    _workplane = True
    _iconName = 'Assembly_ConstraintColinear.svg'
    _tooltip='Add a "{}" constraint to make to line colinear'


class BaseSketch(Base):
    _id = -1
    _toolbarName = 'Assembly3 Sketch Constraints'


class SketchPlane(BaseSketch):
    _id = 38
    _iconName = 'Assembly_ConstraintSketchPlane.svg'
    _tooltip='Add a "{0}" to define the work plane of any draft element\n'\
             'inside or following this constraint. Add an empty "{0}" to\n'\
             'undefine the previous work plane'

    @classmethod
    def getEntityDef(cls,elements,checkCount,obj=None):
        _ = checkCount
        _ = obj
        if not elements:
            # If no element, then this constraint serves the prupose of clearing
            # the current sketch plane
            return []

        # if there is any child element in this constraint, we expect the first
        # one to be a planar face or edge to define the work plane. The rest of
        # entities must be from some draft wire or circle/arc 
        #
        # Base.prepare() will call system.addSketchPlane() with all contained
        # element below. However, the default implementation, 
        # SystemExtension.addSketchPlane(),  only really uses the first one,
        # i.e. the one obtained by _wa(), i.e. a tuple of entities
        # (workplane,base,normal).

        return [_wa] + [_d]*(len(elements)-1)


class BaseDraftWire(BaseSketch):
    _id = -1

    @classmethod
    def check(cls,elements,checkCount=False):
        super(BaseDraftWire,cls).check(elements,checkCount)
        if not checkCount:
            return
        for info in elements:
            if utils.isDraftWire(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one linear edge '
                'from a none-subdivided Draft.Wire'.format(
                    cls.getName()))

class LineLength(BaseSketch):
    _id = 34
    _entityDef = (_dl,)
    _workplane = True
    _props = ["Length"]
    _iconName = 'Assembly_ConstraintLineLength.svg'
    _tooltip='Add a "{}" constrain the length of a none-subdivided Draft.Wire'

    @classmethod
    def init(cls,obj):
        info = obj.Proxy.getElementsInfo()[0]
        obj.Length = info.Shape.Edge1.Length

    @classmethod
    def prepare(cls,obj,solver):
        func = PointsDistance.constraintFunc(obj,solver)
        if func:
            _,p0,p1 = cls.getEntities(obj,solver,retAll=True)[0]
            params = cls.getPropertyValues(obj) + [p0,p1]
            ret = func(*params,group=solver.group)
            solver.system.log('{}: {}'.format(cstrName(obj),ret))
            return ret
        else:
            logger.warn('{} no constraint func'.format(cstrName(obj)))


class EqualLength(BaseDraftWire):
    _id = 9
    _entityDef = (_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualLength.svg'
    _tooltip='Add a "{}" constraint to make two lines of the same length.'


class LengthRatio(BaseDraftWire):
    _id = 10
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Ratio"]
    _iconName = 'Assembly_ConstraintLengthRatio.svg'
    _tooltip='Add a "{}" to constrain the length ratio of two lines.'


class LengthDifference(BaseDraftWire):
    _id = 11
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Difference"]
    _iconName = 'Assembly_ConstraintLengthDifference.svg'
    _tooltip='Add a "{}" to constrain the length difference of two lines.'


class EqualLengthPointLineDistance(BaseSketch):
    _id = 12
    _entityDef = (_p,_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintLengthEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n' \
             'line to be the same as the length of a another line.'


class EqualLineArcLength(BaseSketch):
    _id = 15
    _entityDef = (_l,_a)
    _workplane = True
    _tooltip='Add a "{}" constraint to make a line of the same length as an arc'

    @classmethod
    def check(cls,elements,checkCount=False):
        super(EqualLineArcLength,cls).check(elements,checkCount)
        if not checkCount:
            return
        for i,info in enumerate(elements):
            if i:
                if utils.isDraftCircle(info.Part):
                    return
            elif utils.isDraftWire(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one '
            'non-subdivided Draft.Wire or one Draft.Circle'.format(
                cls.getName()))


class MidPoint(BaseSketch):
    _id = 20
    _entityDef = (_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintMidPoint.svg'
    _tooltip='Add a "{}" to constrain a point to the middle point of a line.'


class Diameter(BaseSketch):
    _id = 25
    _entityDef = (_dc,)
    _props = ("Diameter",)
    _iconName = 'Assembly_ConstraintDiameter.svg'
    _tooltip='Add a "{}" to constrain the diameter of a circle/arc'


class EqualRadius(BaseSketch):
    _id = 33
    _entityDef = (_c,_c)
    _iconName = 'Assembly_ConstraintEqualRadius.svg'
    _tooltip='Add a "{}" constraint to make two circles/arcs of the same radius'

    @classmethod
    def check(cls,elements,checkCount=False):
        super(EqualRadius,cls).check(elements,checkCount)
        if not checkCount:
            return
        for info in elements:
            if utils.isDraftCircle(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one '
            'Draft.Circle'.format(cls.getName()))

#  class CubicLineTangent(BaseSketch):
#      _id = 31
#
#
#  class CurvesTangent(BaseSketch):
#      _id = 32


