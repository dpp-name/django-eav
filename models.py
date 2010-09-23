#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4 coding=utf-8
#
#    This software is derived from EAV-Django originally written and 
#    copyrighted by Andrey Mikhaylenko <http://pypi.python.org/pypi/eav-django>
#
#    This is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This software is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with EAV-Django.  If not, see <http://gnu.org/licenses/>.

import inspect
import re
from datetime import datetime

from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.conf import settings

from .validators import *
from .fields import EavSlugField, EavDatatypeField

def get_unique_class_identifier(cls):
    '''
    Return a unique identifier for a class
    '''
    return '.'.join((inspect.getfile(cls), cls.__name__))


class EnumValue(models.Model):
    value = models.CharField(_(u"value"), db_index=True,
                             unique=True, max_length=50)

    def __unicode__(self):
        return self.value


class EnumGroup(models.Model):
    name = models.CharField(_(u"name"), unique=True, max_length=100)

    enums = models.ManyToManyField(EnumValue, verbose_name=_(u"enum group"))

    def __unicode__(self):
        return self.name


class Attribute(models.Model):
    '''
    The A model in E-A-V. This holds the 'concepts' along with the data type
    something like:

    >>> Attribute.objects.create(name='Height', datatype='float')
    <Attribute: Height (Float)>

    >>> Attribute.objects.create(name='Color', datatype='text', slug='color')
    <Attribute: Color (Text)>
    '''
    class Meta:
        ordering = ['name']

    TYPE_TEXT = 'text'
    TYPE_FLOAT = 'float'
    TYPE_INT = 'int'
    TYPE_DATE = 'date'
    TYPE_BOOLEAN = 'bool'
    TYPE_OBJECT = 'object'
    TYPE_ENUM = 'enum'

    DATATYPE_CHOICES = (
        (TYPE_TEXT, _(u"Text")),
        (TYPE_FLOAT, _(u"Float")),
        (TYPE_INT, _(u"Integer")),
        (TYPE_DATE, _(u"Date")),
        (TYPE_BOOLEAN, _(u"True / False")),
        (TYPE_OBJECT, _(u"Django Object")),
        (TYPE_ENUM,    _(u"Multiple Choice")),
    )

    name = models.CharField(_(u"name"), max_length=100,
                            help_text=_(u"User-friendly attribute name"))

    slug = EavSlugField(_(u"slug"), max_length=50, db_index=True,
                          help_text=_(u"Short unique attribute label"),
                          unique=True)

    description = models.CharField(_(u"description"), max_length=256,
                                     blank=True, null=True,
                                     help_text=_(u"Short description"))

    enum_group = models.ForeignKey(EnumGroup, verbose_name=_(u"choice group"),
                                   blank=True, null=True)

    @property
    def help_text(self):
        return self.description

    datatype = EavDatatypeField(_(u"data type"), max_length=6,
                                choices=DATATYPE_CHOICES)

    created = models.DateTimeField(_(u"created"), default=datetime.now,
                                   editable=False)

    modified = models.DateTimeField(_(u"modified"), auto_now=True)

    required = models.BooleanField(_(u"required"), default=False)


    def get_validators(self):
        DATATYPE_VALIDATORS = {
            'text': validate_text,
            'float': validate_float,
            'int': validate_int,
            'date': validate_date,
            'bool': validate_bool,
            'object': validate_object,
            'enum': validate_enum,
        }

        validation_function = DATATYPE_VALIDATORS[self.datatype]
        return [validation_function]

    def validate_value(self, value):
        for validator in self.get_validators():
            validator(value)
        if self.datatype == self.TYPE_ENUM:
            if value not in self.enum_group.enums.all():
                raise ValidationError(_(u"%(enum)s is not a valid choice "
                                        u"for %(attr)s") % \
                                       {'enum': value, 'attr': self})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = EavSlugField.create_slug_from_name(self.name)
        self.full_clean()
        super(Attribute, self).save(*args, **kwargs)

    def clean(self):
        if self.datatype == self.TYPE_ENUM and not self.enum_group:
            raise ValidationError(_(
                u"You must set the choice group for multiple choice" \
                u"attributes"))

        if self.datatype != self.TYPE_ENUM and self.enum_group:
            raise ValidationError(_(
                u"You can only assign a choice group to multiple choice " \
                u"attributes"))

    def get_choices(self):
        '''
        Returns the avilable choices for enums.
        '''
        if not self.datatype == Attribute.TYPE_ENUM:
            return None
        return self.enum_group.enums.all()

    def save_value(self, entity, value):
        ct = ContentType.objects.get_for_model(entity)
        try:
            value_obj = self.value_set.get(entity_ct=ct,
                                           entity_id=entity.pk,
                                           attribute=self)
        except Value.DoesNotExist:
            if value == None or value == '':
                return
            value_obj = Value.objects.create(entity_ct=ct,
                                             entity_id=entity.pk,
                                             attribute=self)
        if value == None or value == '':
            value_obj.delete()
            return

        if value != value_obj.value:
            value_obj.value = value
            value_obj.save()


    def __unicode__(self):
        return u"%s (%s)" % (self.name, self.get_datatype_display())


class Value(models.Model):
    '''
    The V model in E-A-V. This holds the 'value' for an attribute and an
    entity:

    >>> from django.db import models
    >>> from django.contrib.auth.models import User
    >>> from .registry import Registry
    >>> Registry.register(User)
    >>> u = User.objects.create(username='crazy_dev_user')
    >>> a = Attribute.objects.create(name='Favorite Drink', datatype='text',
    ... slug='fav_drink')
    >>> Value.objects.create(entity=u, attribute=a, value_text='red bull')
    <Value: crazy_dev_user - Favorite Drink: "red bull">

    '''

    class Meta:
        unique_together = ('entity_ct', 'entity_id', 'attribute')


    entity_ct = models.ForeignKey(ContentType, related_name='value_entities')
    entity_id = models.IntegerField()
    entity = generic.GenericForeignKey(ct_field='entity_ct',
                                       fk_field='entity_id')

    value_text = models.TextField(blank=True, null=True)
    value_float = models.FloatField(blank=True, null=True)
    value_int = models.IntegerField(blank=True, null=True)
    value_date = models.DateTimeField(blank=True, null=True)
    value_bool = models.NullBooleanField(blank=True, null=True)
    value_enum = models.ForeignKey(EnumValue, blank=True, null=True,
                                   related_name='eav_values')

    generic_value_id = models.IntegerField(blank=True, null=True)
    generic_value_ct = models.ForeignKey(ContentType, blank=True, null=True,
                                         related_name='value_values')
    value_object = generic.GenericForeignKey(ct_field='generic_value_ct',
                                             fk_field='generic_value_id')

    created = models.DateTimeField(_(u"created"), default=datetime.now)
    modified = models.DateTimeField(_(u"modified"), auto_now=True)

    attribute = models.ForeignKey(Attribute, db_index=True,
                                  verbose_name=_(u"attribute"))


    def save(self, *args, **kwargs):
        self.full_clean()
        super(Value, self).save(*args, **kwargs)

    def clean(self):
        if self.attribute.datatype == Attribute.TYPE_ENUM and \
           self.value_enum:
            if self.value_enum not in self.attribute.enum_group.enums.all():
                raise ValidationError(_(u"%(choice)s is not a valid " \
                                        u"choice for %s(attribute)") % \
                                        {'choice': self.value_enum,
                                         'attribute': self.attribute})

    # TODO: Remove
    def _blank(self):
        """
            Set all the field to none
        """
        for field in self._meta.fields:
            if field.name.startswith('value_') and field.null == True:
                setattr(self, field.name, None)

    def _get_value(self):
        """
            Get returns the Python object hold by this Value object.
        """
        return getattr(self, 'value_%s' % self.attribute.datatype)


    def _set_value(self, new_value):
        self._blank()
        setattr(self, 'value_%s' % self.attribute.datatype, new_value)

    value = property(_get_value, _set_value)

    def __unicode__(self):
        return u"%s - %s: \"%s\"" % (self.entity, self.attribute.name, self.value)


class Entity(object):

    def __init__(self, instance):
        self.model = instance
        self.ct = ContentType.objects.get_for_model(instance)

    def __getattr__(self, name):
        if not name.startswith('_'):
            try:
                attribute = self.get_attribute_by_slug(name)
            except Attribute.DoesNotExist:
                raise AttributeError(_(u"%(obj)s has no EAV attribute named " \
                                       u"'%(attr)s'") % \
                                     {'obj':self.model, 'attr':name})
            try:
                return self.get_value_by_attribute(attribute).value
            except Value.DoesNotExist:
                return None
        return getattr(super(Entity, self), name)

    def get_all_attributes(self):
        return self.model._eav_config_cls.get_attributes()

    def save(self):
        for attribute in self.get_all_attributes():
            if hasattr(self, attribute.slug):
                attribute_value = getattr(self, attribute.slug)
                attribute.save_value(self.model, attribute_value)

    def validate_attributes(self):
        for attribute in self.get_all_attributes():
            value = getattr(self, attribute.slug, None)
            if value is None:
                if attribute.required:
                    raise ValidationError(_(u"%(attr)s EAV field cannot " \
                                            u"be blank") % \
                                            {'attr': attribute.slug})
            else:
                try:
                    attribute.validate_value(value)
                except ValidationError, e:
                    raise ValidationError(_(u"%(attr)s EAV field %(err)s") % \
                                            {'attr': attribute.slug,
                                             'err': e})

    def get_values(self):
        '''
        Get all set EAV Value objects for self.model
        '''
        return Value.objects.filter(entity_ct=self.ct,
                                    entity_id=self.model.pk).select_related()

    def get_all_attribute_slugs(self):
        return self.get_all_attributes().values_list('slug', Flat=True)

    def get_attribute_by_slug(self, slug):
        return self.get_all_attributes().get(slug=slug)

    def get_value_by_attribute(self, attribute):
        return self.get_values().get(attribute=attribute)

    def __iter__(self):
        return iter(self.get_values())

    @staticmethod
    def post_save_handler(sender, *args, **kwargs):
        instance = kwargs['instance']
        entity = getattr(instance, instance._eav_config_cls.eav_attr)
        entity.save()

    @staticmethod
    def pre_save_handler(sender, *args, **kwargs):
        instance = kwargs['instance']
        entity = getattr(kwargs['instance'], instance._eav_config_cls.eav_attr)
        entity.validate_attributes()

if 'django_nose' in settings.INSTALLED_APPS:
    '''
    The django_nose test runner won't automatically create our Patient model
    database table which is required for tests, unless we import it here.

    Please, someone tell me a better way to do this.
    '''
    from .tests.models import Patient, Encounter
