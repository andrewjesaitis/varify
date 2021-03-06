from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf.urls import patterns, url
from django.http import Http404
from django.views.decorators.cache import never_cache
from django.core.urlresolvers import reverse
from restlib2 import resources
from varify import api
from .models import Gene


class GeneResource(resources.Resource):
    model = Gene

    template = api.templates.Gene

    def is_not_found(self, request, response, pk):
        return not self.model.objects.filter(pk=pk).exists()

    @api.cache_resource
    def get(self, request, pk):
        related = ['chr', 'detail', 'families']

        try:
            gene = self.model.objects.select_related(*related).get(pk=pk)
        except self.model.DoesNotExist:
            raise Http404
        data = utils.serialize(gene, **self.template)
        # The approved symbol and name is listed as a synonym for easier
        # searching, but they should be displayed in the output
        data['synonyms'].remove(data['name'])
        data['synonyms'].remove(data['symbol'])
        return data


class GeneSearchResource(resources.Resource):
    model = Gene

    template = api.templates.GeneSearch

    def get(self, request):
        query = request.GET.get('query')
        fuzzy = request.GET.get('fuzzy', 1)
        page = request.GET.get('page', 1)

        # Use only the currently 'approved' genes
        genes = self.model.objects.select_related('synonyms')

        # Perform search if a query string is supplied
        if query:
            if fuzzy == '0' or fuzzy == 'false':
                genes = genes.filter(symbol__iexact=query)
            else:
                genes = genes.filter(synonyms__label__icontains=query)
            genes = genes.distinct()

        # Paginate the results
        paginator = Paginator(genes, api.PAGE_SIZE)

        try:
            page = page = paginator.page(page)
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        resp = {
            'result_count': paginator.count,
            'results': utils.serialize(page.object_list, **self.template),
        }

        # Post procesing..
        for obj in resp['results']:
            # The approved symbol and name is listed as a synonym for easier
            # searching, but they should be displayed in the output
            obj['synonyms'].remove(obj['name'])
            obj['synonyms'].remove(obj['symbol'])

            obj['_links'] = {
                'self': {
                    'rel': 'self',
                    'href': reverse('api:genes:gene',
                        kwargs={'pk': obj['id']})
                }
            }

        links = {}
        if page.number != 1:
            links['prev'] = {
                'rel': 'prev',
                'href': reverse('api:genes:search') + \
                    '?page=' + str(page.number - 1)
            }
        if page.number < paginator.num_pages - 1:
            links['next'] = {
                'rel': 'next',
                'href': reverse('api:genes:search') + \
                    '?page=' + str(page.number + 1)
            }
        if links:
            resp['_links'] = links
        return resp


gene_resource = never_cache(GeneResource())
gene_search_resource = never_cache(GeneSearchResource())

urlpatterns = patterns('',
    url(r'^$', gene_search_resource, name='search'),
    url(r'^(?P<pk>\d+)/$', gene_resource, name='gene'),
)
