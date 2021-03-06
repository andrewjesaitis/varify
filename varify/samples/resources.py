from copy import deepcopy
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf.urls import patterns, url
from django.core.cache import cache
from django.http import Http404
from django.core.urlresolvers import reverse
from django.views.decorators.cache import never_cache
from restlib2 import resources
from varify.variants.resources import VariantResource
from varify import api
from varify.assessments.models import Assessment, Pathogenicity, AssessmentCategory
from .models import Sample, Result
from preserialize.serialize import serialize


class SampleResource(resources.Resource):
    model = Sample

    template = api.templates.Sample

    def is_not_found(self, request, response, pk):
        return not self.model.objects.filter(pk=pk).exists()

    @api.cache_resource
    def get(self, request, pk):
        try:
            sample = self.model.objects.select_related('batch', 'project').get(pk=pk)
        except self.model.DoesNotExist:
            raise Http404

        data = serialize(sample, **self.template)
        data['_links'] = {
            'self': {
                'rel': 'self',
                'href': reverse('api:samples:sample',
                    kwargs={'pk': pk})
            },
            'variants': {
                'rel': 'related',
                'href': reverse('api:samples:variants',
                    kwargs={'pk': pk}),
            }
        }
        return data


class NamedSampleResource(resources.Resource):
    "Resource for looking up a sample by project, batch, and sample name"
    model = Sample

    template = api.templates.Sample

    def is_not_found(self, request, response, project, batch, sample):
        try:
            instance = self.model.objects.get(project__name=project,
                batch__name=batch, name=sample)
        except self.model.DoesNotExist:
            return True

        request.instance = instance
        return False

    def get(self, request, project, batch, sample):
        data = utils.serialize(request.instance, **self.template)
        data['_links'] = {
            'self': {
                'rel': 'self',
                'href': reverse('api:samples:sample',
                    kwargs={'pk': request.instance.pk})
            },
            'variants': {
                'rel': 'related',
                'href': reverse('api:samples:variants',
                    kwargs={'pk': request.instance.pk}),
            }
        }
        return data


class SampleResultsResource(resources.Resource):
    "Paginated view of results for a sample."
    model = Result

    template = api.templates.SampleResult

    def is_not_found(self, request, response, pk):
        return not Sample.objects.filter(pk=pk).exists()

    def get(self, request, pk):
        page = request.GET.get('page', 1)

        related = ['sample', 'variant', 'variant__chr', 'genotype']
        results = self.model.objects.select_related(*related)\
            .filter(sample__pk=pk)

        # Paginate the results
        paginator = Paginator(results, api.PAGE_SIZE)

        try:
            page = page = paginator.page(page)
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        resp = {
            'result_count': paginator.count,
            'results': serialize(page.object_list, **self.template),
        }

        # Augment the links
        for obj in resp['results']:
            obj['_links'] = {
                'self': {
                    'rel': 'self',
                    'href': reverse('api:samples:variant',
                        kwargs={'pk': obj['id']})
                },
                'sample': {
                    'rel': 'related',
                    'href': reverse('api:samples:sample',
                        kwargs={'pk': obj['sample']['id']})
                },
                'variant': {
                    'rel': 'related',
                    'href': reverse('api:variants:variant',
                        kwargs={'pk': obj['variant_id']}),
                }
            }
            obj.pop('variant_id')

        links = {}
        if page.number != 1:
            links['prev'] = {
                'rel': 'prev',
                'href': reverse('api:samples:variants',
                    kwargs={'pk': pk}) + '?page=' + str(page.number - 1)
            }
        if page.number < paginator.num_pages - 1:
            links['next'] = {
                'rel': 'next',
                'href': reverse('api:samples:variants',
                    kwargs={'pk': pk}) + '?page=' + str(page.number + 1)
            }
        if links:
            resp['_links'] = links
        return resp


class SampleResultResource(resources.Resource):
    model = Result

    template = api.templates.SampleResultVariant

    def is_not_found(self, request, response, pk):
        return not self.model.objects.filter(pk=pk).exists()

    def _cache_data(self, request, pk, key):
        related = ['sample', 'variant', 'genotype']

        try:
            result = self.model.objects.select_related(*related).get(pk=pk)
        except self.model.DoesNotExist:
            raise Http404

        data = serialize(result, **self.template)

        data['_links'] = {
            'self': {
                'rel': 'self',
                'href': reverse('api:samples:variant',
                    kwargs={'pk': data['id']})
            },
            'sample': {
                'rel': 'related',
                'href': reverse('api:samples:sample',
                    kwargs={'pk': data['sample']['id']})
            },
            'variant': {
                'rel': 'related',
                'href': reverse('api:variants:variant',
                    kwargs={'pk': data['variant_id']}),
            }
        }

        # Integrate the Variant resource data
        data['variant'] = VariantResource.get(request, data['variant_id'])
        data.pop('variant_id')

        cache.set(key, data, timeout=api.CACHE_TIMEOUT)
        return data

    def get(self, request, pk):
        key = api.cache_key(self.model, pk)
        data = cache.get(key)

        if data is None:
            data = self._cache_data(request, pk, key)

        try:
            assessment = Assessment.objects.get(sample_result=pk, user=request.user.id)
            data['assessment'] = serialize(assessment, **api.templates.ResultAssessment)
        except Assessment.DoesNotExist:
            data['assessment'] = {}

        return data


sample_resource = never_cache(SampleResource())
named_sample_resource = never_cache(NamedSampleResource())
sample_results_resource = never_cache(SampleResultsResource())
sample_result_resource = never_cache(SampleResultResource())

urlpatterns = patterns('',
    url(r'^(?P<pk>\d+)/$', sample_resource, name='sample'),
    url(r'^(?P<project>.+)/(?P<batch>.+)/(?P<sample>.+)/$', named_sample_resource, name='named_sample'),
    url(r'^(?P<pk>\d+)/variants/$', sample_results_resource, name='variants'),
    url(r'^variants/(?P<pk>\d+)/$', sample_result_resource, name='variant'),
)
